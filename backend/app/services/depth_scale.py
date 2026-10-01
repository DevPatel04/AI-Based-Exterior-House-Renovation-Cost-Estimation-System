"""Depth Anything V2 scale helpers (MassingPro-inspired, API-based).

Uses Hugging Face Inference (or Replicate) to get a depth map, then:
- Refines facade aspect / default size when the user has no tape measure
- Applies a mild foreshortening correction per region from relative depth

No local GPU — Railway stays CPU-only.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
from fastapi.concurrency import run_in_threadpool
from PIL import Image

from app.core.config import get_settings


@dataclass
class DepthScaleInfo:
    facade_width_ft: float
    facade_height_ft: float
    depth_map: np.ndarray | None  # HxW float 0..1, higher = farther (or nearer — we normalize)
    method: str
    confidence: float


def _normalize_depth(arr: np.ndarray) -> np.ndarray:
    d = arr.astype(np.float32)
    d = np.nan_to_num(d, nan=0.0, posinf=0.0, neginf=0.0)
    lo, hi = float(np.percentile(d, 2)), float(np.percentile(d, 98))
    if hi <= lo + 1e-6:
        return np.zeros_like(d, dtype=np.float32)
    d = np.clip((d - lo) / (hi - lo), 0.0, 1.0)
    return d


def _decode_depth_image(content: bytes, size: tuple[int, int]) -> np.ndarray | None:
    try:
        img = Image.open(io.BytesIO(content))
        # Prefer raw depth if 16-bit / float; else grayscale
        if img.mode not in {"L", "I", "F", "I;16"}:
            img = img.convert("L")
        arr = np.array(img, dtype=np.float32)
        if arr.shape[0] != size[1] or arr.shape[1] != size[0]:
            img = Image.fromarray(arr.astype(np.uint8) if arr.max() <= 255 else arr)
            img = img.resize(size, Image.BILINEAR)
            arr = np.array(img, dtype=np.float32)
        return _normalize_depth(arr)
    except Exception:
        return None


def _hf_depth_sync(image_path: Path) -> np.ndarray | None:
    settings = get_settings()
    token = (settings.hf_token or "").strip()
    if not token:
        return None
    model = (settings.depth_model or "depth-anything/Depth-Anything-V2-Small-hf").strip()
    try:
        img = Image.open(image_path).convert("RGB")
        img.thumbnail((768, 768))
        size = img.size  # (w, h)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        body = buf.getvalue()
    except Exception:
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "image/jpeg",
    }
    urls = [
        f"https://router.huggingface.co/hf-inference/models/{model}",
    ]
    try:
        with httpx.Client(timeout=120.0) as client:
            for url in urls:
                resp = client.post(url, headers=headers, content=body)
                if resp.status_code == 503:
                    import time

                    time.sleep(8)
                    resp = client.post(url, headers=headers, content=body)
                if resp.status_code >= 400:
                    continue
                ctype = resp.headers.get("content-type", "")
                if "image" in ctype:
                    return _decode_depth_image(resp.content, size)
                # Some endpoints return JSON with base64
                try:
                    data = resp.json()
                except Exception:
                    return _decode_depth_image(resp.content, size)
                if isinstance(data, dict):
                    b64 = data.get("depth") or data.get("image") or data.get("mask")
                    if isinstance(b64, str):
                        raw = b64.split(",", 1)[-1] if "," in b64 else b64
                        try:
                            return _decode_depth_image(base64.b64decode(raw), size)
                        except Exception:
                            continue
                if isinstance(data, list) and data:
                    # unexpected — skip
                    continue
            return None
    except Exception:
        return None


def _replicate_depth_sync(image_path: Path) -> np.ndarray | None:
    """Optional Replicate Depth Anything if HF fails and REPLICATE_API_TOKEN is set."""
    settings = get_settings()
    token = (settings.replicate_api_token or "").strip()
    if not token:
        return None
    try:
        img = Image.open(image_path).convert("RGB")
        img.thumbnail((768, 768))
        size = img.size
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None

    model = (settings.replicate_depth_model or "chenxwh/depth-anything-v2").strip()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "wait=60",
    }
    payload = {"input": {"image": data_uri}}
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"https://api.replicate.com/v1/models/{model}/predictions",
                headers=headers,
                json=payload,
            )
            if resp.status_code >= 400:
                return None
            data = resp.json()
            # Prefer wait response; else poll
            output = data.get("output")
            status = (data.get("status") or "").lower()
            get_url = data.get("urls", {}).get("get") or data.get("urls", {}).get("get")
            if not output and get_url:
                for _ in range(40):
                    import time

                    time.sleep(2)
                    st = client.get(get_url, headers={"Authorization": f"Bearer {token}"})
                    if st.status_code >= 400:
                        return None
                    body = st.json()
                    status = (body.get("status") or "").lower()
                    if status == "succeeded":
                        output = body.get("output")
                        break
                    if status in {"failed", "canceled"}:
                        return None
            if not output:
                return None
            # output may be URL or list
            url = output[0] if isinstance(output, list) else output
            if not isinstance(url, str):
                return None
            if url.startswith("data:"):
                raw = base64.b64decode(url.split(",", 1)[-1])
                return _decode_depth_image(raw, size)
            img_resp = client.get(url, timeout=60.0)
            if img_resp.status_code >= 400:
                return None
            return _decode_depth_image(img_resp.content, size)
    except Exception:
        return None


def _suggest_facade_ft(
    depth: np.ndarray | None,
    image_width: int | None,
    image_height: int | None,
    known_width_ft: float | None,
    known_height_ft: float | None,
) -> tuple[float, float, str, float]:
    """Return (width_ft, height_ft, method, confidence)."""
    settings = get_settings()
    default_w = 30.0
    default_h = 22.0

    if known_width_ft and known_height_ft:
        return known_width_ft, known_height_ft, "user_reference", 0.95
    if known_width_ft:
        # Infer height from image aspect (MassingPro-lite frontal assumption)
        if image_width and image_height and image_width > 0:
            aspect = image_height / image_width
            return known_width_ft, round(known_width_ft * aspect, 2), "user_width_x_image_aspect", 0.8
        return known_width_ft, default_h, "user_width_default_height", 0.7
    if known_height_ft:
        if image_width and image_height and image_height > 0:
            aspect = image_width / image_height
            return round(known_height_ft * aspect, 2), known_height_ft, "user_height_x_image_aspect", 0.8
        return default_w, known_height_ft, "user_height_default_width", 0.7

    # No tape measure — use depth + aspect to nudge defaults (not a true metric reconstruct)
    w, h = default_w, default_h
    method = "default_facade_30x22"
    conf = 0.45
    if image_width and image_height and image_width > 0:
        aspect = image_height / image_width
        # Keep width ~30 ft; height follows photo aspect (clamped for low-rise)
        h = float(np.clip(w * aspect, 14.0, 40.0))
        method = "default_width_x_image_aspect"
        conf = 0.5

    if depth is not None:
        # Frontal facade tends to have lower depth variance in the center band
        hh, ww = depth.shape
        cy0, cy1 = int(hh * 0.25), int(hh * 0.85)
        cx0, cx1 = int(ww * 0.15), int(ww * 0.85)
        center = depth[cy0:cy1, cx0:cx1]
        if center.size:
            var = float(np.var(center))
            # Slightly boost confidence when depth looks planar (low variance)
            if var < 0.04:
                conf = min(0.72, conf + 0.15)
                method = f"{method}+depth_planar"
            else:
                conf = max(0.4, conf - 0.05)
                method = f"{method}+depth_varied"
        # Optional: door-height prior from settings if central vertical span looks tall
        door_h = float(settings.default_door_height_ft)
        if door_h > 0 and image_height:
            # Heuristic unused for absolute scale without a detected door; keep aspect-based
            pass

    return round(w, 2), round(h, 2), method, conf


def region_depth_factor(depth: np.ndarray | None, points: list[dict]) -> float:
    """
    Foreshortening-ish correction: regions farther than the facade median
    get a modest area boost (perspective). Clamped to avoid wild estimates.
    """
    if depth is None or not points:
        return 1.0
    h, w = depth.shape
    ys = [int(np.clip(p["y"], 0, 0.999) * h) for p in points]
    xs = [int(np.clip(p["x"], 0, 0.999) * w) for p in points]
    if not xs or not ys:
        return 1.0
    y0, y1 = max(0, min(ys)), min(h, max(ys) + 1)
    x0, x1 = max(0, min(xs)), min(w, max(xs) + 1)
    patch = depth[y0:y1, x0:x1]
    if patch.size == 0:
        return 1.0
    region_d = float(np.median(patch))
    facade_d = float(np.median(depth[int(h * 0.25) : int(h * 0.85), int(w * 0.15) : int(w * 0.85)]))
    if facade_d < 1e-4:
        return 1.0
    # Relative depth ratio; square for area. Invert if model encodes nearer=brighter.
    ratio = region_d / facade_d
    # Prefer mild correction only
    factor = float(np.clip(ratio**2, 0.75, 1.35))
    return factor


def _refine_sync(
    image_path: Path | None,
    image_width: int | None,
    image_height: int | None,
    known_width_ft: float | None,
    known_height_ft: float | None,
) -> DepthScaleInfo:
    settings = get_settings()
    depth = None
    if settings.enable_depth_scale and image_path is not None and image_path.exists():
        depth = _hf_depth_sync(image_path)
        if depth is None:
            depth = _replicate_depth_sync(image_path)

    w, h, method, conf = _suggest_facade_ft(
        depth, image_width, image_height, known_width_ft, known_height_ft
    )
    if depth is not None and "depth" not in method:
        method = f"{method}+depth_map"
    return DepthScaleInfo(
        facade_width_ft=w,
        facade_height_ft=h,
        depth_map=depth,
        method=method,
        confidence=conf,
    )


async def refine_facade_scale(
    image_path: Path | None,
    image_width: int | None = None,
    image_height: int | None = None,
    known_width_ft: float | None = None,
    known_height_ft: float | None = None,
) -> DepthScaleInfo:
    return await run_in_threadpool(
        _refine_sync,
        image_path,
        image_width,
        image_height,
        known_width_ft,
        known_height_ft,
    )
