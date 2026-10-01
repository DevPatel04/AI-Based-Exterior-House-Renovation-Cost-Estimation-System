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
    # "shop" on CMP is often ground-floor clutter — skip, don't promote to wall
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
    "shop",
}

# Higher = preferred when overlapping same-type boxes
_SOURCE_RANK = {
    "cmp": 100,
    "grounded_sam": 80,
    "ade": 60,
    "segformer": 50,
    "opencv_enrich": 40,
    "opencv_fallback": 20,
}

_IOU_BY_TYPE = {
    RegionType.window.value: 0.40,
    RegionType.gate.value: 0.35,
    RegionType.balcony.value: 0.45,
    RegionType.railing.value: 0.45,
    RegionType.pillar.value: 0.45,
    RegionType.roof_edge.value: 0.50,
    RegionType.parapet.value: 0.50,
    RegionType.main_wall.value: 0.60,
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
        # Openings: open only — close merges adjacent windows into one blob
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
            min_area_frac = 0.0008
        elif region_type in {RegionType.gate.value, RegionType.pillar.value, RegionType.railing.value}:
            min_area_frac = 0.0015
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


def _parse_hf_segmentation(payload, width: int, height: int, source: str = "segformer") -> list[dict]:
    regions: list[dict] = []
    items = payload if isinstance(payload, list) else [payload]
    for item in items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("class") or item.get("entity") or "")
        rtype = _map_label(label)
        if not rtype:
            if label:
                logger.info("DETECT unmapped SegFormer label=%s source=%s", label, source)
            continue
        score = item.get("score")
        if score is None:
            score = 0.75
        mask = _decode_mask(item.get("mask"), height, width)
        if mask is None:
            continue
        for reg in _mask_to_regions(mask, rtype, _pretty_label(rtype, label), float(score)):
            reg["source"] = source
            regions.append(reg)

    walls = [r for r in regions if r["region_type"] == RegionType.main_wall.value]
    others = [r for r in regions if r["region_type"] != RegionType.main_wall.value]
    if len(walls) > 1:
        walls.sort(key=lambda r: _poly_area(r["points"]), reverse=True)
        walls = walls[:2]
    return walls + others


def _source_rank(reg: dict) -> int:
    src = str(reg.get("source") or "").lower()
    for key, rank in _SOURCE_RANK.items():
        if key in src:
            return rank
    return 30


def _iou_threshold_for(rtype: str) -> float:
    return float(_IOU_BY_TYPE.get(rtype, 0.50))


def _center_inside(inner: list[dict], outer: list[dict]) -> bool:
    if len(inner) < 3 or len(outer) < 3:
        return True
    cx = sum(p["x"] for p in inner) / len(inner)
    cy = sum(p["y"] for p in inner) / len(inner)
    xs = [p["x"] for p in outer]
    ys = [p["y"] for p in outer]
    return min(xs) - 0.02 <= cx <= max(xs) + 0.02 and min(ys) - 0.02 <= cy <= max(ys) + 0.02


def _union_bbox_points(a: list[dict], b: list[dict]) -> list[dict]:
    xs = [p["x"] for p in a] + [p["x"] for p in b]
    ys = [p["y"] for p in a] + [p["y"] for p in b]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    return [
        {"x": round(x0, 4), "y": round(y0, 4)},
        {"x": round(x1, 4), "y": round(y0, 4)},
        {"x": round(x1, 4), "y": round(y1, 4)},
        {"x": round(x0, 4), "y": round(y1, 4)},
    ]


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
    """
    Merge detections with class-aware NMS and source priority.
    Prefer CMP openings over ADE; union overlapping walls; drop parts outside facade.
    """
    merged: list[dict] = []
    for lst in lists:
        for r in lst or []:
            merged.append(dict(r))

    walls = [r for r in merged if r["region_type"] == RegionType.main_wall.value]
    parts = [r for r in merged if r["region_type"] != RegionType.main_wall.value]

    # Prefer higher-source walls; union overlaps into one facade box
    walls.sort(key=lambda r: (_source_rank(r), _poly_area(r["points"])), reverse=True)
    wall_kept: list[dict] = []
    for w in walls:
        hit = None
        for k in wall_kept:
            if _iou_norm(k["points"], w["points"]) > _iou_threshold_for(RegionType.main_wall.value):
                hit = k
                break
        if hit is None:
            wall_kept.append(w)
            continue
        # Union into the preferred wall
        if _source_rank(w) > _source_rank(hit) or (
            _source_rank(w) == _source_rank(hit) and _poly_area(w["points"]) > _poly_area(hit["points"])
        ):
            hit["points"] = _union_bbox_points(hit["points"], w["points"])
            hit["confidence"] = max(float(hit.get("confidence") or 0), float(w.get("confidence") or 0))
            hit["source"] = w.get("source") or hit.get("source")
        else:
            hit["points"] = _union_bbox_points(hit["points"], w["points"])
            hit["confidence"] = max(float(hit.get("confidence") or 0), float(w.get("confidence") or 0))
    wall_kept = wall_kept[:2]

    # Prefer CMP openings: drop lower-source duplicates of same type
    parts.sort(
        key=lambda r: (_source_rank(r), float(r.get("confidence") or 0.5)),
        reverse=True,
    )
    kept: list[dict] = []
    for r in parts:
        thr = _iou_threshold_for(r["region_type"])
        dup = next(
            (
                k
                for k in kept
                if k["region_type"] == r["region_type"] and _iou_norm(k["points"], r["points"]) > thr
            ),
            None,
        )
        if dup is not None:
            continue
        # If CMP already has this opening, skip ADE-only near-duplicates of any opening type
        if str(r.get("source") or "").startswith("ade"):
            if any(
                k["region_type"] == r["region_type"]
                and _source_rank(k) >= _SOURCE_RANK["cmp"]
                and _iou_norm(k["points"], r["points"]) > 0.25
                for k in kept
            ):
                continue
        # Parts should sit on the facade when a wall exists
        if wall_kept and r["region_type"] in {
            RegionType.window.value,
            RegionType.gate.value,
            RegionType.balcony.value,
            RegionType.pillar.value,
        }:
            if not any(_center_inside(r["points"], w["points"]) for w in wall_kept):
                continue
        kept.append(r)

    win_i = 0
    win_total = sum(1 for x in kept if x["region_type"] == RegionType.window.value)
    for r in kept:
        if r["region_type"] == RegionType.window.value:
            win_i += 1
            r["label"] = f"Window {win_i}" if win_total > 1 else "Window"

    logger.info(
        "DETECT merge walls=%s parts=%s (windows=%s doors=%s) sources=%s",
        len(wall_kept),
        len(kept),
        sum(1 for r in kept if r["region_type"] == RegionType.window.value),
        sum(1 for r in kept if r["region_type"] == RegionType.gate.value),
        sorted({str(r.get("source")) for r in wall_kept + kept}),
    )
    return wall_kept + kept


def _wall_bbox_px(regions: list[dict], w: int, h: int) -> tuple[int, int, int, int]:
    walls = [r for r in regions if r["region_type"] == RegionType.main_wall.value]
    if not walls:
        return int(w * 0.1), int(h * 0.1), int(w * 0.9), int(h * 0.9)
    # Prefer highest-confidence / largest wall
    walls = sorted(walls, key=lambda r: (_source_rank(r), _poly_area(r["points"])), reverse=True)
    pts = walls[0]["points"]
    xs = [p["x"] for p in pts]
    ys = [p["y"] for p in pts]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    # 2% pad
    pad_x = (x1 - x0) * 0.02
    pad_y = (y1 - y0) * 0.02
    return (
        max(0, int((x0 - pad_x) * w)),
        max(0, int((y0 - pad_y) * h)),
        min(w, int((x1 + pad_x) * w)),
        min(h, int((y1 + pad_y) * h)),
    )


def enrich_with_opencv_parts(image_rgb: np.ndarray, regions: list[dict]) -> list[dict]:
    """
    Find rectangular openings (windows/doors) inside the facade bbox.
    Runs when openings look incomplete — not only on wall-only results.
    """
    windows = [r for r in regions if r["region_type"] == RegionType.window.value]
    doors = [r for r in regions if r["region_type"] == RegionType.gate.value]
    mean_win_conf = (
        sum(float(r.get("confidence") or 0.5) for r in windows) / len(windows) if windows else 0.0
    )
    # Enrich unless we already have a solid opening set
    if len(windows) >= 4 and len(doors) >= 1 and mean_win_conf >= 0.7:
        return regions

    h, w = image_rgb.shape[:2]
    x0, y0, x1, y1 = _wall_bbox_px(regions, w, h)
    pad_x = int((x1 - x0) * 0.04)
    pad_y = int((y1 - y0) * 0.06)
    x0, y0 = max(0, x0 + pad_x), max(0, y0 + pad_y)
    x1, y1 = min(w - 1, x1 - pad_x), min(h - 1, y1 - pad_y)
    if x1 - x0 < 40 or y1 - y0 < 40:
        return regions

    crop = image_rgb[y0:y1, x0:x1]
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    # CLAHE helps dark glass / weathered plaster
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray_eq = clahe.apply(gray)
    gray_blur = cv2.GaussianBlur(gray_eq, (5, 5), 0)
    edges = cv2.Canny(gray_blur, 40, 120)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)

    # Dark recessed openings (windows) via blackhat
    kernel_bh = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    blackhat = cv2.morphologyEx(gray_eq, cv2.MORPH_BLACKHAT, kernel_bh)
    _, dark = cv2.threshold(blackhat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)

    facade_area = float(max(1, (x1 - x0) * (y1 - y0)))
    max_windows = max(6, min(12, int(facade_area / 8000)))
    candidates: list[tuple[float, dict]] = []

    def _add_contour(c, score_bonus: float = 0.0) -> None:
        area = float(cv2.contourArea(c))
        if area < facade_area * 0.0015 or area > facade_area * 0.28:
            return
        rx, ry, rw, rh = cv2.boundingRect(c)
        if rw < 14 or rh < 14:
            return
        aspect = rw / max(1, rh)
        rectangularity = area / max(1.0, float(rw * rh))
        if rectangularity < 0.28 or not (0.30 <= aspect <= 3.5):
            return

        abs_x0, abs_y0 = x0 + rx, y0 + ry
        abs_x1, abs_y1 = abs_x0 + rw, abs_y0 + rh
        if abs_x0 <= x0 + 2 or abs_y0 <= y0 + 2 or abs_x1 >= x1 - 2 or abs_y1 >= y1 - 2:
            if area > facade_area * 0.12:
                return

        # Interior darkness vs surrounding wall (glass/recessed)
        pad = 2
        inner = gray[max(0, ry + pad) : max(0, ry + rh - pad), max(0, rx + pad) : max(0, rx + rw - pad)]
        darkness = 0.0
        if inner.size:
            darkness = max(0.0, (float(np.mean(gray_eq)) - float(np.mean(inner))) / 255.0)

        cy_facade = (abs_y0 + abs_y1) / 2
        cy_norm = cy_facade / h
        # Door: tall, near lower band of facade (not mid-floor tall windows)
        facade_h = max(1, y1 - y0)
        near_ground = (abs_y1 - y0) / facade_h > 0.55 and cy_norm > 0.55
        if aspect < 0.65 and rh > rw * 1.4 and near_ground:
            rtype = RegionType.gate.value
            label = "Door / gate"
        else:
            rtype = RegionType.window.value
            label = "Window"

        score = rectangularity * min(1.0, area / (facade_area * 0.02)) + darkness * 0.5 + score_bonus
        candidates.append(
            (
                score,
                {
                    "region_type": rtype,
                    "label": label,
                    "points": _bbox_points(abs_x0, abs_y0, abs_x1, abs_y1, w, h),
                    "confidence": round(min(0.72, 0.45 + score * 0.2), 3),
                    "source": "opencv_enrich",
                },
            )
        )

    contours_e, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours_e:
        _add_contour(c, score_bonus=0.0)
    contours_d, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours_d:
        _add_contour(c, score_bonus=0.15)

    candidates.sort(key=lambda t: t[0], reverse=True)
    added: list[dict] = []
    for _score, reg in candidates:
        rtype = reg["region_type"]
        if rtype == RegionType.window.value and sum(
            1 for a in added if a["region_type"] == RegionType.window.value
        ) >= max_windows:
            continue
        if rtype == RegionType.gate.value and any(a["region_type"] == RegionType.gate.value for a in added):
            continue
        if any(_iou_norm(a["points"], reg["points"]) > 0.4 for a in added):
            continue
        if any(
            r["region_type"] != RegionType.main_wall.value and _iou_norm(r["points"], reg["points"]) > 0.4
            for r in regions
        ):
            continue
        added.append(reg)

    # Roof band only when a strong horizontal edge sits in the top of the facade
    if not any(r["region_type"] == RegionType.roof_edge.value for r in regions + added):
        top_band = edges[: max(4, int(edges.shape[0] * 0.15)), :]
        row_sum = top_band.sum(axis=1) if top_band.size else np.array([])
        if row_sum.size and float(row_sum.max()) > float(np.mean(row_sum) + 2 * np.std(row_sum)):
            band_h = max(8, int((y1 - y0) * 0.08))
            added.append(
                {
                    "region_type": RegionType.roof_edge.value,
                    "label": "Roof edge",
                    "points": _bbox_points(x0, max(0, y0 - band_h // 2), x1, y0 + band_h, w, h),
                    "confidence": 0.5,
                    "source": "opencv_enrich",
                }
            )

    wins = [a for a in added if a["region_type"] == RegionType.window.value]
    for i, a in enumerate(wins, start=1):
        a["label"] = f"Window {i}" if len(wins) > 1 else "Window"

    if added:
        logger.info(
            "OpenCV enrich added %s parts (want more openings: had windows=%s doors=%s conf=%.2f)",
            len(added),
            len(windows),
            len(doors),
            mean_win_conf,
        )
    return _merge_region_lists(regions, added)


def detect_opencv_fallback(image_path: Path) -> list[dict]:
    """
    Last-resort detector when HF/Replicate are unavailable.
    Places a facade wall box on the central image band, then finds windows/doors.
    """
    try:
        pil = Image.open(image_path).convert("RGB")
        settings = get_settings()
        edge = int(getattr(settings, "detect_max_edge", 0) or 1280)
        pil.thumbnail((edge, edge))
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

    detect_edge = int(getattr(settings, "detect_max_edge", 0) or 1280)
    detect_edge = max(768, min(detect_edge, int(settings.upload_max_edge or 1600)))
    try:
        # Full-res for OpenCV enrich; downscale copy for HF
        full = Image.open(image_path).convert("RGB")
        full_rgb = np.array(full)
        pil = full.copy()
        pil.thumbnail((detect_edge, detect_edge))
        width, height = pil.size
        rgb = np.array(pil)
        buf = io.BytesIO()
        pil.save(buf, format="JPEG", quality=92)
        body = buf.getvalue()
    except Exception as exc:
        raise StructureDetectError(f"Could not read project image: {exc}") from exc

    primary = (settings.segformer_model or "nvidia/segformer-b0-finetuned-ade-512-512").strip()
    cmp_model = "Xpitfire/segformer-finetuned-segments-cmp-facade"
    ade_model = "nvidia/segformer-b0-finetuned-ade-512-512"
    # CMP first for windows/doors/balcony; ADE for solid facade wall
    models: list[tuple[str, str]] = []
    for m, tag in (
        (cmp_model, "cmp"),
        (primary, "ade" if "ade" in primary.lower() else "segformer"),
        (ade_model, "ade"),
    ):
        if m and all(m != existing for existing, _ in models):
            models.append((m, tag))

    collected: list[list[dict]] = []
    cmp_openings = 0
    with httpx.Client(timeout=90.0) as client:
        for model, tag in models:
            # If CMP already found openings, skip duplicate ADE pass when primary == ADE
            if tag == "ade" and cmp_openings >= 3 and collected:
                logger.info("DETECT skip %s — CMP already found %s openings", model, cmp_openings)
                # Still want one ADE wall if we have no wall yet
                has_wall = any(
                    r["region_type"] == RegionType.main_wall.value for lst in collected for r in lst
                )
                if has_wall:
                    continue
            data = _call_hf_image_segmentation(client, model, body, token)
            if data is None:
                continue
            regions = _parse_hf_segmentation(data, width, height, source=tag)
            if regions:
                n_open = sum(1 for r in regions if r["region_type"] != RegionType.main_wall.value)
                logger.info(
                    "SegFormer (%s/%s) → %s regions (%s non-wall)",
                    tag,
                    model.split("/")[-1],
                    len(regions),
                    n_open,
                )
                if tag == "cmp":
                    cmp_openings = n_open
                collected.append(regions)

    if not collected:
        raise StructureDetectError(
            "SegFormer returned no facade regions for this photo. "
            "Try a clearer front-facing exterior, or draw regions manually."
        )

    merged = _merge_region_lists(*collected)
    # OpenCV on full-res facade crop (scaled region coords from detect size → full)
    scale_x = full_rgb.shape[1] / max(1, width)
    scale_y = full_rgb.shape[0] / max(1, height)
    if abs(scale_x - 1.0) > 0.02 or abs(scale_y - 1.0) > 0.02:
        # Regions are in detect-image normalized space (= same 0..1 as full)
        pass
    merged = enrich_with_opencv_parts(full_rgb, merged)
    return merged


async def detect_segformer_regions(image_path: Path) -> list[dict]:
    return await run_in_threadpool(_detect_segformer_sync, image_path)
