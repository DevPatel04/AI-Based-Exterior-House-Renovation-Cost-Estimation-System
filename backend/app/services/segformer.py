"""SegFormer CMP-facade structure detection via Hugging Face Inference API.

No local GPU / torch required — Railway stays CPU-only.
Falls back gracefully when HF_TOKEN is missing or the call fails.
"""

from __future__ import annotations

import io
from pathlib import Path

import cv2
import httpx
import numpy as np
from fastapi.concurrency import run_in_threadpool
from PIL import Image

from app.core.config import get_settings
from app.models import RegionType

# CMP facade / SegFormer label → our RegionType
_LABEL_MAP: dict[str, str] = {
    "facade": RegionType.main_wall.value,
    "wall": RegionType.main_wall.value,
    "main_wall": RegionType.main_wall.value,
    "window": RegionType.window.value,
    "windows": RegionType.window.value,
    "door": RegionType.gate.value,
    "gate": RegionType.gate.value,
    "balcony": RegionType.balcony.value,
    "pillar": RegionType.pillar.value,
    "column": RegionType.pillar.value,
    "parapet": RegionType.parapet.value,
    "cornice": RegionType.roof_edge.value,
    "roof": RegionType.roof_edge.value,
    "roof_edge": RegionType.roof_edge.value,
    "railing": RegionType.railing.value,
    "sill": RegionType.other.value,
    "molding": RegionType.other.value,
    "deco": RegionType.other.value,
    "blind": RegionType.window.value,
    "shop": RegionType.main_wall.value,
}

_SKIP_LABELS = {"background", "sky", "unlabeled", "void"}


def _map_label(label: str) -> str | None:
    key = (label or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key in _SKIP_LABELS or key.startswith("background"):
        return None
    if key in _LABEL_MAP:
        return _LABEL_MAP[key]
    for needle, rtype in _LABEL_MAP.items():
        if needle in key:
            return rtype
    return RegionType.other.value


def _mask_to_polygon(mask: np.ndarray, min_area_frac: float = 0.002) -> list[dict] | None:
    """Largest contour of a binary mask → normalized polygon points."""
    h, w = mask.shape[:2]
    if h == 0 or w == 0:
        return None
    binary = (mask > 0).astype(np.uint8) * 255
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    area = float(cv2.contourArea(contour))
    if area < (h * w * min_area_frac):
        return None
    peri = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, 0.012 * peri, True)
    if len(approx) < 3:
        # Fallback: axis-aligned bbox as quad
        x, y, bw, bh = cv2.boundingRect(contour)
        pts = [(x, y), (x + bw, y), (x + bw, y + bh), (x, y + bh)]
    else:
        # Cap vertices for Konva usability
        if len(approx) > 10:
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
        pts = [(int(p[0][0]), int(p[0][1])) for p in approx]
        if len(pts) < 3:
            return None

    return [{"x": round(px / w, 4), "y": round(py / h, 4)} for px, py in pts]


def _decode_mask(mask_field, height: int, width: int) -> np.ndarray | None:
    """HF may return base64 PNG, raw bytes, or nested dict with base64."""
    import base64

    raw: bytes | None = None
    if isinstance(mask_field, str):
        data = mask_field
        if "," in data and data.strip().startswith("data:"):
            data = data.split(",", 1)[1]
        try:
            raw = base64.b64decode(data)
        except Exception:
            return None
    elif isinstance(mask_field, dict):
        # e.g. {"mask": "base64..."} or pillow-like
        inner = mask_field.get("mask") or mask_field.get("image") or mask_field.get("data")
        return _decode_mask(inner, height, width) if inner is not None else None
    elif isinstance(mask_field, (bytes, bytearray)):
        raw = bytes(mask_field)
    else:
        return None

    try:
        img = Image.open(io.BytesIO(raw)).convert("L")
        arr = np.array(img)
        if arr.shape[0] != height or arr.shape[1] != width:
            arr = np.array(img.resize((width, height), Image.NEAREST))
        return arr
    except Exception:
        return None


def _parse_hf_segmentation(payload, width: int, height: int) -> list[dict]:
    regions: list[dict] = []
    items = payload if isinstance(payload, list) else [payload]
    for item in items:
        if not isinstance(item, dict):
            continue
        label = item.get("label") or item.get("class") or item.get("entity") or ""
        rtype = _map_label(str(label))
        if not rtype:
            continue
        score = float(item.get("score") or item.get("confidence") or 0.7)
        mask = _decode_mask(item.get("mask"), height, width)
        if mask is None:
            continue
        points = _mask_to_polygon(mask)
        if not points:
            continue
        regions.append(
            {
                "region_type": rtype,
                "label": str(label).replace("_", " ").title(),
                "points": points,
                "confidence": min(0.95, max(0.4, score)),
                "source": "segformer",
            }
        )
    return regions


def _detect_segformer_sync(image_path: Path) -> list[dict]:
    settings = get_settings()
    token = (settings.hf_token or "").strip()
    if not token or not settings.enable_segformer:
        return []

    model = (settings.segformer_model or "Xpitfire/segformer-finetuned-segments-cmp-facade").strip()
    try:
        img = Image.open(image_path).convert("RGB")
        # Keep inference snappy / under HF payload limits
        img.thumbnail((1024, 1024))
        width, height = img.size
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        body = buf.getvalue()
    except Exception:
        return []

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "image/jpeg",
        "Accept": "application/json",
    }
    # Prefer new router; fall back to classic inference URL
    urls = [
        f"https://router.huggingface.co/hf-inference/models/{model}",
        f"https://api-inference.huggingface.co/models/{model}",
    ]

    try:
        with httpx.Client(timeout=120.0) as client:
            data = None
            for url in urls:
                resp = client.post(url, headers=headers, content=body)
                if resp.status_code == 503:
                    # Model loading — one short retry
                    import time

                    time.sleep(8)
                    resp = client.post(url, headers=headers, content=body)
                if resp.status_code >= 400:
                    continue
                try:
                    data = resp.json()
                except Exception:
                    continue
                if data is not None:
                    break
            if data is None:
                return []
            if isinstance(data, dict) and data.get("error"):
                return []
            return _parse_hf_segmentation(data, width, height)
    except Exception:
        return []


async def detect_segformer_regions(image_path: Path) -> list[dict]:
    return await run_in_threadpool(_detect_segformer_sync, image_path)
