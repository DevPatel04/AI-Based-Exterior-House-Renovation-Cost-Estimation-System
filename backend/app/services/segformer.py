"""SegFormer facade / building structure detection (Hugging Face Inference).

Replaces the old Gemini-polygon + hardcoded DEFAULT_REGIONS path.
Uses semantic masks → OpenCV contours → Konva polygons.

Primary model: nvidia/segformer-b0-finetuned-ade-512-512 (reliable on HF Inference).
Optional CMP facade model can be set via SEGFORMER_MODEL.
"""

from __future__ import annotations

import base64
import io
import logging
import time
from pathlib import Path

import cv2
import httpx
import numpy as np
from fastapi.concurrency import run_in_threadpool
from PIL import Image

from app.core.config import get_settings
from app.models import RegionType

logger = logging.getLogger(__name__)

# ADE20K + CMP-style labels → our RegionType
_LABEL_MAP: dict[str, str] = {
    # ADE / general
    "wall": RegionType.main_wall.value,
    "building": RegionType.main_wall.value,
    "house": RegionType.main_wall.value,
    "skyscraper": RegionType.main_wall.value,
    "windowpane": RegionType.window.value,
    "window": RegionType.window.value,
    "windows": RegionType.window.value,
    "door": RegionType.gate.value,
    "gate": RegionType.gate.value,
    "fence": RegionType.railing.value,
    "railing": RegionType.railing.value,
    "column": RegionType.pillar.value,
    "pillar": RegionType.pillar.value,
    "stairs": RegionType.other.value,
    "stairway": RegionType.other.value,
    "porch": RegionType.balcony.value,
    "balcony": RegionType.balcony.value,
    "awning": RegionType.roof_edge.value,
    "roof": RegionType.roof_edge.value,
    "roof_edge": RegionType.roof_edge.value,
    # CMP facade
    "facade": RegionType.main_wall.value,
    "main_wall": RegionType.main_wall.value,
    "cornice": RegionType.roof_edge.value,
    "parapet": RegionType.parapet.value,
    "sill": RegionType.other.value,
    "molding": RegionType.other.value,
    "deco": RegionType.other.value,
    "blind": RegionType.window.value,
    "shop": RegionType.main_wall.value,
}

_SKIP = {
    "background",
    "sky",
    "tree",
    "grass",
    "plant",
    "earth",
    "ground",
    "road",
    "sidewalk",
    "path",
    "person",
    "car",
    "truck",
    "bus",
    "van",
    "bicycle",
    "motorcycle",
    "water",
    "sea",
    "river",
    "mountain",
    "hill",
    "rock",
    "sand",
    "snow",
    "cloud",
    "unlabeled",
    "void",
    "signboard",
    "pole",
    "streetlight",
    "traffic",
}


class StructureDetectError(Exception):
    """Raised when structure detection cannot produce real masks."""


def _map_label(label: str) -> str | None:
    key = (label or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not key or key in _SKIP:
        return None
    for skip in _SKIP:
        if skip in key:
            return None
    if key in _LABEL_MAP:
        return _LABEL_MAP[key]
    for needle, rtype in _LABEL_MAP.items():
        if needle in key:
            return rtype
    return None


def _clean_mask(mask: np.ndarray) -> np.ndarray:
    binary = (mask > 127).astype(np.uint8) * 255
    kernel = np.ones((5, 5), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
    return binary


def _contour_to_points(contour, w: int, h: int) -> list[dict] | None:
    peri = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, max(2.0, 0.01 * peri), True)
    if len(approx) < 3:
        x, y, bw, bh = cv2.boundingRect(contour)
        if bw < 4 or bh < 4:
            return None
        pts = [(x, y), (x + bw, y), (x + bw, y + bh), (x, y + bh)]
    else:
        if len(approx) > 12:
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
        pts = [(int(p[0][0]), int(p[0][1])) for p in approx]
        if len(pts) < 3:
            return None
    return [
        {"x": round(float(np.clip(px / w, 0, 1)), 4), "y": round(float(np.clip(py / h, 0, 1)), 4)}
        for px, py in pts
    ]


def _mask_to_regions(
    mask: np.ndarray,
    region_type: str,
    label: str,
    score: float,
    min_area_frac: float = 0.004,
    max_parts: int = 8,
) -> list[dict]:
    """Split a class mask into separate connected components (e.g. each window)."""
    h, w = mask.shape[:2]
    binary = _clean_mask(mask)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []

    min_area = h * w * min_area_frac
    # For main wall, keep larger pieces only; for windows allow smaller
    if region_type == RegionType.main_wall.value:
        min_area = h * w * 0.02
    elif region_type == RegionType.window.value:
        min_area = h * w * 0.003

    scored = []
    for c in contours:
        area = float(cv2.contourArea(c))
        if area < min_area:
            continue
        scored.append((area, c))
    scored.sort(key=lambda t: t[0], reverse=True)

    out: list[dict] = []
    for i, (area, contour) in enumerate(scored[:max_parts]):
        points = _contour_to_points(contour, w, h)
        if not points:
            continue
        suffix = f" {i + 1}" if len(scored) > 1 and region_type != RegionType.main_wall.value else ""
        out.append(
            {
                "region_type": region_type,
                "label": f"{label}{suffix}".strip(),
                "points": points,
                "confidence": min(0.95, max(0.45, float(score if score else 0.7))),
                "source": "segformer",
            }
        )
    return out


def _decode_mask(mask_field, height: int, width: int) -> np.ndarray | None:
    raw: bytes | None = None
    if isinstance(mask_field, str):
        data = mask_field.strip()
        if data.startswith("data:"):
            data = data.split(",", 1)[1]
        try:
            raw = base64.b64decode(data)
        except Exception:
            return None
    elif isinstance(mask_field, dict):
        inner = mask_field.get("mask") or mask_field.get("image") or mask_field.get("data")
        return _decode_mask(inner, height, width) if inner is not None else None
    elif isinstance(mask_field, (bytes, bytearray)):
        raw = bytes(mask_field)
    else:
        return None

    try:
        img = Image.open(io.BytesIO(raw)).convert("L")
        if img.size != (width, height):
            img = img.resize((width, height), Image.NEAREST)
        return np.array(img)
    except Exception:
        return None


def _parse_hf_segmentation(payload, width: int, height: int) -> list[dict]:
    regions: list[dict] = []
    items = payload if isinstance(payload, list) else [payload]
    for item in items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("class") or item.get("entity") or "")
        rtype = _map_label(label)
        if not rtype:
            continue
        score = item.get("score")
        if score is None:
            score = 0.75
        mask = _decode_mask(item.get("mask"), height, width)
        if mask is None:
            continue
        pretty = label.replace("_", " ").title()
        if rtype == RegionType.main_wall.value:
            pretty = "Main wall"
        elif rtype == RegionType.window.value:
            pretty = "Window"
        elif rtype == RegionType.gate.value:
            pretty = "Door / gate"
        elif rtype == RegionType.roof_edge.value:
            pretty = "Roof edge"
        regions.extend(_mask_to_regions(mask, rtype, pretty, float(score)))

    # Prefer one dominant main wall (largest)
    walls = [r for r in regions if r["region_type"] == RegionType.main_wall.value]
    others = [r for r in regions if r["region_type"] != RegionType.main_wall.value]
    if len(walls) > 1:
        walls.sort(key=lambda r: _poly_area(r["points"]), reverse=True)
        walls = walls[:2]  # keep up to 2 large facade planes
    return walls + others


def _poly_area(points: list[dict]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    for i in range(len(points)):
        j = (i + 1) % len(points)
        area += points[i]["x"] * points[j]["y"]
        area -= points[j]["x"] * points[i]["y"]
    return abs(area) / 2.0


def _call_hf_image_segmentation(client: httpx.Client, model: str, body: bytes, token: str) -> list | dict | None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "image/jpeg",
        "Accept": "application/json",
        "X-Wait-For-Model": "true",
    }
    urls = [
        f"https://router.huggingface.co/hf-inference/models/{model}",
        f"https://api-inference.huggingface.co/models/{model}",
        f"https://api-inference.huggingface.co/pipeline/image-segmentation/{model}",
    ]
    last_err = None
    for url in urls:
        for attempt in range(3):
            resp = client.post(url, headers=headers, content=body)
            if resp.status_code == 503:
                time.sleep(5 + attempt * 5)
                continue
            if resp.status_code >= 400:
                last_err = f"{resp.status_code}: {resp.text[:200]}"
                break
            try:
                data = resp.json()
            except Exception as exc:
                last_err = str(exc)
                break
            if isinstance(data, dict) and data.get("error"):
                last_err = str(data.get("error"))
                # model loading
                if "loading" in last_err.lower():
                    time.sleep(8)
                    continue
                break
            return data
    if last_err:
        logger.warning("HF SegFormer failed for %s: %s", model, last_err)
    return None


def _detect_segformer_sync(image_path: Path) -> list[dict]:
    settings = get_settings()
    token = (settings.hf_token or "").strip()
    if not token:
        raise StructureDetectError(
            "HF_TOKEN is not set. Add a Hugging Face token (https://huggingface.co/settings/tokens) "
            "on the Railway backend so SegFormer can detect structure regions."
        )
    if not settings.enable_segformer:
        raise StructureDetectError("ENABLE_SEGFORMER is false. Turn it on to detect structure regions.")

    try:
        img = Image.open(image_path).convert("RGB")
        img.thumbnail((1024, 1024))
        width, height = img.size
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92)
        body = buf.getvalue()
    except Exception as exc:
        raise StructureDetectError(f"Could not read project image: {exc}") from exc

    primary = (settings.segformer_model or "nvidia/segformer-b0-finetuned-ade-512-512").strip()
    # Try primary, then ADE, then CMP facade
    models = [primary]
    for alt in (
        "nvidia/segformer-b0-finetuned-ade-512-512",
        "Xpitfire/segformer-finetuned-segments-cmp-facade",
    ):
        if alt not in models:
            models.append(alt)

    with httpx.Client(timeout=180.0) as client:
        for model in models:
            data = _call_hf_image_segmentation(client, model, body, token)
            if data is None:
                continue
            regions = _parse_hf_segmentation(data, width, height)
            if regions:
                logger.info("SegFormer (%s) returned %s regions", model, len(regions))
                return regions

    raise StructureDetectError(
        "SegFormer returned no facade regions for this photo. "
        "Try a clearer front-facing exterior (less tree occlusion), or draw regions manually."
    )


async def detect_segformer_regions(image_path: Path) -> list[dict]:
    return await run_in_threadpool(_detect_segformer_sync, image_path)
