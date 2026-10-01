"""SegFormer facade structure detection (Hugging Face Inference).

ADE SegFormer often labels the whole house as one "building" mask.
We therefore:
  1) Run CMP facade + ADE models and merge labels
  2) Punch opening masks out of the wall so windows stay separate
  3) Caller may enrich with Replicate Grounded-SAM / DINO when openings are thin
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
        RegionType.balcony.value,
    }
    binary = _clean_mask(mask, soft=soft)
    # TREE finds separate window panes inside larger facade blobs
    mode = cv2.RETR_TREE if soft else cv2.RETR_EXTERNAL
    contours, _ = cv2.findContours(binary, mode, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []

    if min_area_frac is None:
        if region_type == RegionType.main_wall.value:
            min_area_frac = 0.02
        elif region_type == RegionType.window.value:
            min_area_frac = 0.00035
        elif region_type in {
            RegionType.gate.value,
            RegionType.pillar.value,
            RegionType.railing.value,
            RegionType.balcony.value,
        }:
            min_area_frac = 0.0008
        else:
            min_area_frac = 0.002

    min_area = h * w * min_area_frac
    scored = []
    for c in contours:
        area = float(cv2.contourArea(c))
        if area < min_area:
            continue
        if region_type != RegionType.main_wall.value and area > h * w * 0.45:
            continue
        scored.append((area, c))
    scored.sort(key=lambda t: t[0], reverse=True)

    out: list[dict] = []
    for i, (_area, contour) in enumerate(scored[:max_parts]):
        if region_type in {
            RegionType.window.value,
            RegionType.gate.value,
            RegionType.balcony.value,
            RegionType.pillar.value,
        }:
            x, y, bw, bh = cv2.boundingRect(contour)
            if bw < 8 or bh < 8:
                continue
            aspect = bw / max(1, bh)
            if region_type == RegionType.window.value and not (0.25 <= aspect <= 4.5):
                continue
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
    """Parse HF masks; punch openings out of wall so the wall doesn't swallow windows."""
    by_type: dict[str, list[tuple[np.ndarray, float, str]]] = {}
    items = payload if isinstance(payload, list) else [payload]
    for item in items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("class") or item.get("entity") or "")
        rtype = _map_label(label)
        if not rtype:
            continue
        score = float(item.get("score") if item.get("score") is not None else 0.75)
        mask = _decode_mask(item.get("mask"), height, width)
        if mask is None:
            continue
        by_type.setdefault(rtype, []).append((mask, score, label))

    opening_types = {
        RegionType.window.value,
        RegionType.gate.value,
        RegionType.balcony.value,
        RegionType.railing.value,
        RegionType.pillar.value,
    }
    openings = np.zeros((height, width), dtype=np.uint8)
    for rtype in opening_types:
        for mask, _score, _label in by_type.get(rtype, []):
            openings = np.maximum(openings, (mask > 127).astype(np.uint8) * 255)

    regions: list[dict] = []
    for rtype, entries in by_type.items():
        for mask, score, label in entries:
            work = mask
            if rtype == RegionType.main_wall.value and openings.any():
                work = mask.copy()
                work[openings > 0] = 0
            regions.extend(_mask_to_regions(work, rtype, _pretty_label(rtype, label), score))

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
    source_rank = {
        "gemini_refine": 5,
        "gemini_vision": 4,
        "replicate_grounded_sam": 4,
        "replicate_grounding_dino": 3,
        "segformer": 2,
        "grounded_sam": 2,
    }

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


def _format_network_error(exc: Exception, service: str) -> str:
    msg = str(exc)
    low = msg.lower()
    if "name or service not known" in low or "no address associated" in low or "temporary failure in name resolution" in low or "errno -5" in low or "errno -3" in low:
        return (
            f"Cannot reach {service} (DNS/network). "
            "Railway backend must have outbound HTTPS. Redeploy the service, "
            "confirm HF_TOKEN / REPLICATE_API_TOKEN are set on this backend service, "
            "or draw regions manually."
        )
    if "timed out" in low or "timeout" in low:
        return f"{service} timed out. Try again in a minute or draw regions manually."
    return f"{service} error: {msg[:180]}"


def _call_hf_image_segmentation(client: httpx.Client, model: str, body: bytes, token: str) -> list | dict | None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "image/jpeg",
        "Accept": "application/json",
        "X-Wait-For-Model": "true",
    }
    # Classic inference host first; router is newer and sometimes flaky
    urls = [
        f"https://api-inference.huggingface.co/models/{model}",
        f"https://api-inference.huggingface.co/pipeline/image-segmentation/{model}",
        f"https://router.huggingface.co/hf-inference/models/{model}",
    ]
    last_err = None
    t0 = time.perf_counter()
    logger.info("DETECT hf_call start model=%s bytes=%s", model, len(body))
    for url in urls:
        for attempt in range(3):
            try:
                resp = client.post(url, headers=headers, content=body)
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError, OSError) as exc:
                last_err = _format_network_error(exc, "Hugging Face")
                logger.warning(
                    "DETECT hf_call connect_fail model=%s url=%s attempt=%s err=%s",
                    model,
                    url,
                    attempt + 1,
                    exc,
                )
                break
            if resp.status_code == 503:
                logger.info(
                    "DETECT hf_call model_loading model=%s attempt=%s status=503",
                    model,
                    attempt + 1,
                )
                time.sleep(5 + attempt * 5)
                continue
            if resp.status_code >= 400:
                last_err = f"{resp.status_code}: {resp.text[:200]}"
                logger.warning(
                    "DETECT hf_call http_error model=%s status=%s body=%s",
                    model,
                    resp.status_code,
                    resp.text[:200],
                )
                break
            try:
                data = resp.json()
            except Exception as exc:
                last_err = str(exc)
                break
            if isinstance(data, dict) and data.get("error"):
                last_err = str(data.get("error"))
                if "loading" in last_err.lower():
                    logger.info("DETECT hf_call still_loading model=%s err=%s", model, last_err)
                    time.sleep(8)
                    continue
                break
            ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                "DETECT hf_call ok model=%s ms=%s segments=%s",
                model,
                ms,
                len(data) if isinstance(data, list) else "dict",
            )
            return data
    ms = int((time.perf_counter() - t0) * 1000)
    if last_err:
        logger.warning("DETECT hf_call fail model=%s ms=%s err=%s", model, ms, last_err)
        # Propagate network errors so the API can show them clearly
        if "Cannot reach Hugging Face" in last_err or "timed out" in last_err.lower():
            raise StructureDetectError(last_err)
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

    from app.services.detect_log import format_summary

    collected: list[list[dict]] = []
    network_err: str | None = None
    logger.info(
        "DETECT segformer begin image=%s size=%sx%s models=%s",
        image_path.name,
        width,
        height,
        models,
    )
    with httpx.Client(timeout=180.0) as client:
        for model in models:
            try:
                data = _call_hf_image_segmentation(client, model, body, token)
            except StructureDetectError as exc:
                network_err = str(exc)
                logger.error("DETECT segformer model_abort model=%s err=%s", model, exc)
                continue
            if data is None:
                logger.warning("DETECT segformer model_empty model=%s", model)
                continue
            regions = _parse_hf_segmentation(data, width, height)
            if regions:
                logger.info(
                    "DETECT segformer model_ok model=%s %s",
                    model,
                    format_summary(regions),
                )
                collected.append(regions)
            else:
                logger.warning("DETECT segformer parse_empty model=%s", model)

    if not collected:
        if network_err:
            raise StructureDetectError(network_err)
        raise StructureDetectError(
            "SegFormer returned no facade regions for this photo. "
            "Try a clearer front-facing exterior, or draw regions manually."
        )

    merged = _merge_region_lists(*collected)
    logger.info("DETECT segformer merged %s", format_summary(merged))
    return merged


async def detect_segformer_regions(image_path: Path) -> list[dict]:
    return await run_in_threadpool(_detect_segformer_sync, image_path)
