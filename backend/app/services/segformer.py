"""SegFormer facade structure detection (Hugging Face Inference).

ADE SegFormer often labels the whole house as one "building" mask.
We therefore:
  1) Run ADE + CMP models and merge labels
  2) Enrich walls-only results with OpenCV window/door/roof candidates
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

_LABEL_MAP: dict[str, str] = {
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
    "facade": RegionType.main_wall.value,
    "main_wall": RegionType.main_wall.value,
    "cornice": RegionType.roof_edge.value,
    "parapet": RegionType.parapet.value,
    "sill": RegionType.window.value,  # window sill → treat near window
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
    "ceiling",
    "floor",
    "carpet",
    "sofa",
    "chair",
    "table",
    "bed",
    "cabinet",
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


def _pretty_label(rtype: str, raw: str) -> str:
    defaults = {
        RegionType.main_wall.value: "Main wall",
        RegionType.window.value: "Window",
        RegionType.gate.value: "Door / gate",
        RegionType.balcony.value: "Balcony",
        RegionType.roof_edge.value: "Roof edge",
        RegionType.railing.value: "Railing",
        RegionType.pillar.value: "Pillar",
        RegionType.parapet.value: "Parapet",
    }
    return defaults.get(rtype) or raw.replace("_", " ").title()


def _clean_mask(mask: np.ndarray, soft: bool = False) -> np.ndarray:
    binary = (mask > 127).astype(np.uint8) * 255
    if soft:
        kernel = np.ones((3, 3), np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)
        return binary
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


def _bbox_points(x0: int, y0: int, x1: int, y1: int, w: int, h: int) -> list[dict]:
    return [
        {"x": round(float(np.clip(x0 / w, 0, 1)), 4), "y": round(float(np.clip(y0 / h, 0, 1)), 4)},
        {"x": round(float(np.clip(x1 / w, 0, 1)), 4), "y": round(float(np.clip(y0 / h, 0, 1)), 4)},
        {"x": round(float(np.clip(x1 / w, 0, 1)), 4), "y": round(float(np.clip(y1 / h, 0, 1)), 4)},
        {"x": round(float(np.clip(x0 / w, 0, 1)), 4), "y": round(float(np.clip(y1 / h, 0, 1)), 4)},
    ]


def _mask_to_regions(
    mask: np.ndarray,
    region_type: str,
    label: str,
    score: float,
    min_area_frac: float | None = None,
    max_parts: int = 12,
) -> list[dict]:
    h, w = mask.shape[:2]
    soft = region_type in {
        RegionType.window.value,
        RegionType.gate.value,
        RegionType.railing.value,
        RegionType.pillar.value,
    }
    binary = _clean_mask(mask, soft=soft)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []

    if min_area_frac is None:
        if region_type == RegionType.main_wall.value:
            min_area_frac = 0.015
        elif region_type == RegionType.window.value:
            min_area_frac = 0.0005
        elif region_type in {RegionType.gate.value, RegionType.pillar.value, RegionType.railing.value, RegionType.balcony.value}:
            min_area_frac = 0.001
        else:
            min_area_frac = 0.003

    min_area = h * w * min_area_frac
    scored = []
    for c in contours:
        area = float(cv2.contourArea(c))
        if area < min_area:
            continue
        scored.append((area, c))
    scored.sort(key=lambda t: t[0], reverse=True)

    out: list[dict] = []
    for i, (_area, contour) in enumerate(scored[:max_parts]):
        # Prefer axis-aligned boxes for windows/doors (more editable in Konva)
        if region_type in {RegionType.window.value, RegionType.gate.value}:
            x, y, bw, bh = cv2.boundingRect(contour)
            points = _bbox_points(x, y, x + bw, y + bh, w, h)
        else:
            points = _contour_to_points(contour, w, h)
        if not points:
            continue
        suffix = f" {i + 1}" if len(scored) > 1 and region_type != RegionType.main_wall.value else ""
        out.append(
            {
                "region_type": region_type,
                "label": f"{label}{suffix}".strip(),
                "points": points,
                "confidence": min(0.95, max(0.4, float(score if score else 0.7))),
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


def _poly_area(points: list[dict]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    for i in range(len(points)):
        j = (i + 1) % len(points)
        area += points[i]["x"] * points[j]["y"]
        area -= points[j]["x"] * points[i]["y"]
    return abs(area) / 2.0


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
        regions.extend(_mask_to_regions(mask, rtype, _pretty_label(rtype, label), float(score)))

    walls = [r for r in regions if r["region_type"] == RegionType.main_wall.value]
    others = [r for r in regions if r["region_type"] != RegionType.main_wall.value]
    if len(walls) > 1:
        walls.sort(key=lambda r: _poly_area(r["points"]), reverse=True)
        walls = walls[:2]
    return walls + others


def _iou_norm(a: list[dict], b: list[dict]) -> float:
    """Rough IoU from axis-aligned bboxes of polygons."""
    def box(pts):
        xs = [p["x"] for p in pts]
        ys = [p["y"] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    ax0, ay0, ax1, ay1 = box(a)
    bx0, by0, bx1, by1 = box(b)
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(1e-9, (ax1 - ax0) * (ay1 - ay0))
    area_b = max(1e-9, (bx1 - bx0) * (by1 - by0))
    return inter / (area_a + area_b - inter)


def _merge_region_lists(*lists: list[dict]) -> list[dict]:
    """Merge detections; keep non-wall parts; dedupe overlapping same-type boxes."""
    merged: list[dict] = []
    for lst in lists:
        for r in lst or []:
            merged.append(r)

    walls = [r for r in merged if r["region_type"] == RegionType.main_wall.value]
    parts = [r for r in merged if r["region_type"] != RegionType.main_wall.value]

    # One/two largest walls
    walls.sort(key=lambda r: _poly_area(r["points"]), reverse=True)
    walls = walls[:2]

    kept: list[dict] = []
    # Prefer model masks over OpenCV heuristics when overlapping
    source_rank = {"gemini_refine": 3, "segformer": 2, "grounded_sam": 2, "opencv_enrich": 1, "opencv_fallback": 0}

    def _rank(r: dict) -> tuple:
        return (
            source_rank.get(str(r.get("source") or ""), 1),
            float(r.get("confidence") or 0.5),
        )

    for r in sorted(parts, key=_rank, reverse=True):
        if any(
            k["region_type"] == r["region_type"] and _iou_norm(k["points"], r["points"]) > 0.4
            for k in kept
        ):
            continue
        kept.append(r)

    # Renumber window labels
    win_i = 0
    for r in kept:
        if r["region_type"] == RegionType.window.value:
            win_i += 1
            r["label"] = f"Window {win_i}" if win_i > 1 or sum(
                1 for x in kept if x["region_type"] == RegionType.window.value
            ) > 1 else "Window"

    return walls + kept


def _wall_bbox_px(regions: list[dict], w: int, h: int) -> tuple[int, int, int, int]:
    walls = [r for r in regions if r["region_type"] == RegionType.main_wall.value]
    if not walls:
        return int(w * 0.1), int(h * 0.1), int(w * 0.9), int(h * 0.9)
    pts = walls[0]["points"]
    xs = [p["x"] for p in pts]
    ys = [p["y"] for p in pts]
    return (
        int(min(xs) * w),
        int(min(ys) * h),
        int(max(xs) * w),
        int(max(ys) * h),
    )


def _box_contrast_score(gray: np.ndarray, rx: int, ry: int, rw: int, rh: int) -> float:
    """Windows/doors usually differ in texture from surrounding wall."""
    H, W = gray.shape[:2]
    x0, y0 = max(0, rx), max(0, ry)
    x1, y1 = min(W, rx + rw), min(H, ry + rh)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return 0.0
    patch = gray[y0:y1, x0:x1]
    inner = patch[max(1, rh // 8) : max(2, rh - rh // 8), max(1, rw // 8) : max(2, rw - rw // 8)]
    if inner.size < 16:
        inner = patch
    # Border ring around the box (wall context)
    pad = max(4, min(rw, rh) // 4)
    bx0, by0 = max(0, x0 - pad), max(0, y0 - pad)
    bx1, by1 = min(W, x1 + pad), min(H, y1 + pad)
    border = gray[by0:by1, bx0:bx1].copy()
    # zero-out interior so border mean is context only
    iy0, iy1 = y0 - by0, y1 - by0
    ix0, ix1 = x0 - bx0, x1 - bx0
    border[max(0, iy0) : max(0, iy1), max(0, ix0) : max(0, ix1)] = 0
    border_vals = border[border > 0]
    if border_vals.size < 16:
        return float(np.std(inner) / 64.0)
    mean_diff = abs(float(np.mean(inner)) - float(np.mean(border_vals))) / 255.0
    std_inner = float(np.std(inner)) / 64.0
    return float(np.clip(0.55 * mean_diff + 0.45 * min(1.0, std_inner), 0.0, 1.0))


def enrich_with_opencv_parts(image_rgb: np.ndarray, regions: list[dict]) -> list[dict]:
    """
    Find rectangular openings (windows/doors) + roof band inside the facade bbox.
    Tuned for recall: catch most openings; light filters remove obvious junk.
    """
    windows = sum(1 for r in regions if r["region_type"] == RegionType.window.value)
    # Only skip enrich when we already have a solid set of windows
    if windows >= 5:
        return regions

    h, w = image_rgb.shape[:2]
    x0, y0, x1, y1 = _wall_bbox_px(regions, w, h)
    pad_x = int((x1 - x0) * 0.03)
    pad_y = int((y1 - y0) * 0.05)
    x0, y0 = max(0, x0 + pad_x), max(0, y0 + pad_y)
    x1, y1 = min(w - 1, x1 - pad_x), min(h - 1, y1 - pad_y)
    if x1 - x0 < 40 or y1 - y0 < 40:
        return regions

    crop = image_rgb[y0:y1, x0:x1]
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 35, 120)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    facade_area = float(max(1, (x1 - x0) * (y1 - y0)))
    candidates: list[tuple[float, dict]] = []

    for c in contours:
        area = float(cv2.contourArea(c))
        if area < facade_area * 0.002 or area > facade_area * 0.22:
            continue
        rx, ry, rw, rh = cv2.boundingRect(c)
        if rw < 14 or rh < 14:
            continue
        aspect = rw / max(1, rh)
        rectangularity = area / max(1.0, float(rw * rh))
        if rectangularity < 0.30 or not (0.35 <= aspect <= 3.0):
            continue

        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.04 * peri, True)
        quad_bonus = 0.12 if 4 <= len(approx) <= 8 else 0.0

        abs_x0, abs_y0 = x0 + rx, y0 + ry
        abs_x1, abs_y1 = abs_x0 + rw, abs_y0 + rh
        margin = 4
        # Allow near-edge boxes unless they are huge (likely facade outline)
        if (
            abs_x0 <= x0 + margin or abs_y0 <= y0 + margin or abs_x1 >= x1 - margin or abs_y1 >= y1 - margin
        ) and area > facade_area * 0.12:
            continue

        contrast = _box_contrast_score(gray, rx, ry, rw, rh)
        if contrast < 0.10:
            continue

        cy = ((abs_y0 + abs_y1) / 2) / h
        points = _bbox_points(abs_x0, abs_y0, abs_x1, abs_y1, w, h)

        if aspect < 0.7 and rh > rw * 1.3 and cy > 0.48:
            rtype = RegionType.gate.value
            label = "Door / gate"
        else:
            rtype = RegionType.window.value
            label = "Window"

        score = 0.30 * rectangularity + 0.40 * contrast + quad_bonus
        score *= min(1.0, area / (facade_area * 0.01))
        if score < 0.18:
            continue

        candidates.append(
            (
                score,
                {
                    "region_type": rtype,
                    "label": label,
                    "points": points,
                    "confidence": round(min(0.85, 0.4 + score * 0.5), 3),
                    "source": "opencv_enrich",
                    "_area_norm": area / facade_area,
                },
            )
        )

    candidates.sort(key=lambda t: t[0], reverse=True)

    win_areas = [c[1]["_area_norm"] for c in candidates if c[1]["region_type"] == RegionType.window.value]
    median_area = float(np.median(win_areas)) if win_areas else 0.0

    added: list[dict] = []
    for score, reg in candidates:
        rtype = reg["region_type"]
        if rtype == RegionType.window.value:
            if sum(1 for a in added if a["region_type"] == RegionType.window.value) >= 10:
                continue
            # Soft size filter — keep more recall than before
            if median_area > 0 and (
                reg["_area_norm"] < median_area * 0.2 or reg["_area_norm"] > median_area * 5.0
            ):
                continue
        if rtype == RegionType.gate.value and sum(1 for a in added if a["region_type"] == RegionType.gate.value) >= 2:
            continue
        if any(_iou_norm(a["points"], reg["points"]) > 0.45 for a in added):
            continue
        if any(
            r["region_type"] != RegionType.main_wall.value and _iou_norm(r["points"], reg["points"]) > 0.45
            for r in regions
        ):
            continue
        clean = {k: v for k, v in reg.items() if not k.startswith("_")}
        added.append(clean)

    if not any(r["region_type"] == RegionType.roof_edge.value for r in regions + added):
        band_h = max(10, int((y1 - y0) * 0.07))
        added.append(
            {
                "region_type": RegionType.roof_edge.value,
                "label": "Roof edge",
                "points": _bbox_points(x0, max(0, y0 - band_h // 3), x1, y0 + band_h, w, h),
                "confidence": 0.48,
                "source": "opencv_enrich",
            }
        )

    # Balcony heuristic: wide mid-height rectangle with railing-like edge density
    if not any(r["region_type"] == RegionType.balcony.value for r in regions + added):
        mid_y0 = int((y1 - y0) * 0.40)
        mid_y1 = int((y1 - y0) * 0.72)
        mid = gray[mid_y0:mid_y1, :]
        if mid.size:
            mid_edges = cv2.Canny(mid, 40, 120)
            # horizontal projection — balcony rails often make a strong horizontal band
            row_sum = mid_edges.mean(axis=1) if mid_edges.size else np.array([])
            if row_sum.size and float(row_sum.max()) > 18:
                by = int(np.argmax(row_sum))
                bh = max(20, int((y1 - y0) * 0.12))
                abs_y0 = y0 + max(0, mid_y0 + by - bh // 2)
                abs_y1 = min(h - 1, abs_y0 + bh)
                bx0 = x0 + int((x1 - x0) * 0.15)
                bx1 = x0 + int((x1 - x0) * 0.85)
                added.append(
                    {
                        "region_type": RegionType.balcony.value,
                        "label": "Balcony",
                        "points": _bbox_points(bx0, abs_y0, bx1, abs_y1, w, h),
                        "confidence": 0.42,
                        "source": "opencv_enrich",
                    }
                )

    wins = [a for a in added if a["region_type"] == RegionType.window.value]
    for i, a in enumerate(wins, start=1):
        a["label"] = f"Window {i}" if len(wins) > 1 else "Window"

    if added:
        logger.info("OpenCV enrich added %s parts (recall-focused)", len(added))
    return _merge_region_lists(regions, added)


def detect_opencv_fallback(image_path: Path) -> list[dict]:
    """
    Last-resort detector when HF/Replicate are unavailable.
    Places a facade wall box on the central image band, then finds windows/doors.
    """
    try:
        pil = Image.open(image_path).convert("RGB")
        pil.thumbnail((1024, 1024))
        rgb = np.array(pil)
    except Exception as exc:
        raise StructureDetectError(f"Could not read project image: {exc}") from exc

    h, w = rgb.shape[:2]
    # Estimate facade as the densest edge band in the middle of the frame
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    # Ignore outer 5% (often sky/ground margins)
    ys, xs = np.where(edges > 0)
    if len(xs) > 50:
        x0 = int(np.percentile(xs, 8))
        x1 = int(np.percentile(xs, 92))
        y0 = int(np.percentile(ys, 10))
        y1 = int(np.percentile(ys, 90))
    else:
        x0, y0, x1, y1 = int(w * 0.12), int(h * 0.15), int(w * 0.88), int(h * 0.88)

    wall = {
        "region_type": RegionType.main_wall.value,
        "label": "Main wall",
        "points": _bbox_points(x0, y0, x1, y1, w, h),
        "confidence": 0.45,
        "source": "opencv_fallback",
    }
    regions = enrich_with_opencv_parts(rgb, [wall])
    if not regions:
        regions = [wall]
    for r in regions:
        r["source"] = r.get("source") or "opencv_fallback"
    logger.warning("Using OpenCV fallback structure detection (%s regions)", len(regions))
    return regions


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
        pil = Image.open(image_path).convert("RGB")
        pil.thumbnail((1024, 1024))
        width, height = pil.size
        rgb = np.array(pil)
        buf = io.BytesIO()
        pil.save(buf, format="JPEG", quality=92)
        body = buf.getvalue()
    except Exception as exc:
        raise StructureDetectError(f"Could not read project image: {exc}") from exc

    primary = (settings.segformer_model or "nvidia/segformer-b0-finetuned-ade-512-512").strip()
    # CMP first for windows/doors/balcony; ADE for solid facade wall
    models: list[str] = []
    for m in (
        "Xpitfire/segformer-finetuned-segments-cmp-facade",
        primary,
        "nvidia/segformer-b0-finetuned-ade-512-512",
    ):
        if m and m not in models:
            models.append(m)

    collected: list[list[dict]] = []
    with httpx.Client(timeout=180.0) as client:
        for model in models:
            data = _call_hf_image_segmentation(client, model, body, token)
            if data is None:
                continue
            regions = _parse_hf_segmentation(data, width, height)
            if regions:
                logger.info(
                    "SegFormer (%s) → %s regions (%s non-wall)",
                    model,
                    len(regions),
                    sum(1 for r in regions if r["region_type"] != RegionType.main_wall.value),
                )
                collected.append(regions)

    if not collected:
        raise StructureDetectError(
            "SegFormer returned no facade regions for this photo. "
            "Try a clearer front-facing exterior, or draw regions manually."
        )

    merged = _merge_region_lists(*collected)
    merged = enrich_with_opencv_parts(rgb, merged)
    return merged


async def detect_segformer_regions(image_path: Path) -> list[dict]:
    return await run_in_threadpool(_detect_segformer_sync, image_path)
