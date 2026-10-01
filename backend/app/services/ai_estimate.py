"""Gemini-based facade sizing, region areas, and material quantities."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.models import Material, StructureRegion
from app.services.gemini import gemini_vision_json

logger = logging.getLogger(__name__)


def _bbox(points: list[dict]) -> dict:
    xs = [float(p["x"]) for p in (points or [])]
    ys = [float(p["y"]) for p in (points or [])]
    if not xs or not ys:
        return {"x0": 0, "y0": 0, "x1": 0, "y1": 0, "w": 0, "h": 0, "area": 0}
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, h = max(0.0, x1 - x0), max(0.0, y1 - y0)
    return {
        "x0": round(x0, 4),
        "y0": round(y0, 4),
        "x1": round(x1, 4),
        "y1": round(y1, 4),
        "w": round(w, 4),
        "h": round(h, 4),
        "area": round(w * h, 4),
    }


def estimate_facade_and_areas_ai(
    image_path: Path | None,
    regions: list[StructureRegion],
    *,
    known_width_ft: float | None = None,
    known_height_ft: float | None = None,
) -> dict | None:
    """
    Ask Gemini for facade size + per-region areas (sq ft / length).

    Returns:
      {
        facade_width_ft, facade_height_ft, method, confidence,
        regions: {region_id: {area_sq_ft, length_ft|None, include, note}}
      }
    or None if AI unavailable.
    """
    if not regions:
        return None

    region_payload = []
    for r in regions:
        rtype = r.region_type.value if hasattr(r.region_type, "value") else str(r.region_type)
        region_payload.append(
            {
                "region_id": r.id,
                "region_type": rtype,
                "label": r.label or rtype,
                "bbox_norm": _bbox(r.points or []),
                "confidence": float(r.confidence or 0.5),
            }
        )

    hints = []
    if known_width_ft:
        hints.append(f"User says facade width ≈ {known_width_ft} ft")
    if known_height_ft:
        hints.append(f"User says facade height ≈ {known_height_ft} ft")
    hint_txt = "; ".join(hints) if hints else "No tape measure — estimate from the photo."

    prompt = f"""You are a quantity surveyor for residential facade renovation.
Look at the house photo and the detected regions (normalized 0–1 boxes).

Estimate real-world facade size and each region's finished area.

Priors (use when helpful):
- Exterior door / gate opening height ≈ 7 ft
- Typical Indian/suburban low-rise storey ≈ 10–12 ft
- Single-storey cottage width often 20–40 ft
- Windows are usually 8–40 sq ft each; ignore signs, posters, bikes, tiny wall patches

{hint_txt}

Return ONLY JSON:
{{
  "facade_width_ft": number,
  "facade_height_ft": number,
  "confidence": 0 to 1,
  "reason": "short",
  "regions": [
    {{
      "region_id": number,
      "include": true,
      "area_sq_ft": number,
      "length_ft": number or null,
      "note": "short"
    }}
  ]
}}

Rules:
- include=false for false detections (signs, tiny noise < ~4 sq ft windows, blank wall strips mislabeled as gate).
- main_wall area ≈ paint/finish area of that wall face (not whole plot).
- roof_edge: area ≈ band area; length_ft ≈ horizontal roof span.
- gate/railing: set length_ft when linear; area_sq_ft still required.
- One entry per region_id listed below. Be conservative — prefer fewer real openings.

REGIONS:
{json.dumps(region_payload)}
"""

    data = gemini_vision_json(prompt, image_path, temperature=0.15)
    if not isinstance(data, dict):
        return None

    try:
        fw = float(data.get("facade_width_ft") or 0)
        fh = float(data.get("facade_height_ft") or 0)
    except (TypeError, ValueError):
        return None
    if known_width_ft:
        fw = float(known_width_ft)
    if known_height_ft:
        fh = float(known_height_ft)
    if fw < 8 or fw > 120 or fh < 8 or fh > 80:
        logger.warning("AI facade size out of range: %sx%s — rejecting", fw, fh)
        return None

    try:
        conf = float(data.get("confidence") or 0.7)
    except (TypeError, ValueError):
        conf = 0.7

    by_id: dict[int, dict] = {}
    items = data.get("regions") or []
    if not isinstance(items, list):
        items = []
    valid_ids = {r.id for r in regions}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            rid = int(item.get("region_id"))
            area = float(item.get("area_sq_ft") or 0)
        except (TypeError, ValueError):
            continue
        if rid not in valid_ids:
            continue
        include = bool(item.get("include", True))
        length = item.get("length_ft")
        try:
            length_ft = float(length) if length is not None else None
        except (TypeError, ValueError):
            length_ft = None
        # Guard absurd values
        if area < 0 or area > fw * fh * 1.5:
            include = False
        by_id[rid] = {
            "include": include and area >= 1.0,
            "area_sq_ft": round(max(0.0, area), 2),
            "length_ft": round(length_ft, 2) if length_ft is not None and length_ft > 0 else None,
            "note": str(item.get("note") or "")[:120],
        }

    if not by_id:
        return None

    logger.info(
        "AI estimate facade=%.1fx%.1f ft regions=%s included=%s",
        fw,
        fh,
        len(by_id),
        sum(1 for v in by_id.values() if v["include"]),
    )
    return {
        "facade_width_ft": round(fw, 2),
        "facade_height_ft": round(fh, 2),
        "method": "gemini_vision_qs",
        "confidence": min(0.95, max(0.4, conf)),
        "reason": str(data.get("reason") or "")[:200],
        "regions": by_id,
    }


def estimate_quantities_ai(
    image_path: Path | None,
    materials_payload: list[dict],
    areas_summary: list[dict],
    facade_width_ft: float,
    facade_height_ft: float,
) -> dict[int, dict] | None:
    """
    AI quantities keyed by material_id:
      {mid: {base_quantity, wastage_percent, unit, reason}}
    """
    if not materials_payload:
        return None

    prompt = f"""You are a renovation quantity surveyor.
Given facade size ≈ {facade_width_ft} ft × {facade_height_ft} ft, region areas, and assigned materials,
estimate practical purchase quantities (with typical site wastage).

Return ONLY JSON:
{{
  "quantities": [
    {{
      "material_id": number,
      "base_quantity": number,
      "wastage_percent": number,
      "unit": "string matching catalog",
      "reason": "short"
    }}
  ]
}}

Rules:
- Use catalog coverage_per_unit when provided (e.g. paint liters = area / coverage).
- Round sensibly for purchase (e.g. paint to 0.5 L, panels to whole pieces).
- wastage_percent typically 5–15 for finishes, 3–8 for railings.
- Only use material_id values from the list. One row per material_id.

AREAS:
{json.dumps(areas_summary)}

MATERIALS:
{json.dumps(materials_payload)}
"""

    data = gemini_vision_json(prompt, image_path, temperature=0.2)
    if data is None:
        return None
    if isinstance(data, dict):
        items = data.get("quantities") or data.get("items") or []
    elif isinstance(data, list):
        items = data
    else:
        return None
    if not isinstance(items, list):
        return None

    valid = {int(m["material_id"]) for m in materials_payload}
    out: dict[int, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            mid = int(item.get("material_id"))
            base = float(item.get("base_quantity") or 0)
            waste = float(item.get("wastage_percent") or 8)
        except (TypeError, ValueError):
            continue
        if mid not in valid or base < 0:
            continue
        out[mid] = {
            "base_quantity": round(base, 3),
            "wastage_percent": round(min(25.0, max(0.0, waste)), 2),
            "unit": str(item.get("unit") or "").strip() or None,
            "reason": str(item.get("reason") or "AI quantity")[:160],
        }
    return out or None


def material_catalog_row(m: Material) -> dict:
    mt = m.material_type.value if hasattr(m.material_type, "value") else str(m.material_type)
    return {
        "material_id": m.id,
        "name": m.name,
        "material_type": mt,
        "unit": m.unit,
        "coverage_per_unit": float(m.coverage_per_unit or 0) or None,
        "wastage_percent": float(m.wastage_percent or 8),
        "suitable_regions": list(m.suitable_regions or []),
    }
