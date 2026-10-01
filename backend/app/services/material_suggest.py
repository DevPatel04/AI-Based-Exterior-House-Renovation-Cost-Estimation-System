"""Suggest materials per facade region from the project catalog.

Uses Gemini vision (REST) when GEMINI_API_KEY is set + catalog constraints.
Falls back to rule-based picks from suitable_regions only if AI fails.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Material, ProjectImage, StructureRegion
from app.services.gemini import gemini_vision_json

logger = logging.getLogger(__name__)

_DEFAULT_BY_REGION: dict[str, list[str]] = {
    "main_wall": ["paint", "stone_cladding", "panels", "texture_finish", "tiles"],
    "parapet": ["paint", "panels", "texture_finish"],
    "pillar": ["paint", "stone_cladding"],
    "balcony": ["glass_railing", "metal_railing", "tiles"],
    "railing": ["glass_railing", "metal_railing"],
    "roof_edge": ["metal_railing", "glass_railing", "panels"],
    "gate": ["metal_railing", "stone_cladding", "panels"],
    "window": ["paint", "panels"],
    "other": ["paint", "texture_finish", "panels"],
}


def _catalog_materials(db: Session) -> list[Material]:
    return (
        db.query(Material)
        .filter(Material.is_active.is_(True), Material.approved.is_(True))
        .order_by(Material.material_type, Material.name)
        .all()
    )


def _suited(mat: Material, region_type: str) -> bool:
    suited = list(mat.suitable_regions or [])
    if not suited:
        return True
    return region_type in suited or "other" in suited


def _rule_pick(region: StructureRegion, catalog: list[Material]) -> tuple[Material | None, str]:
    rtype = region.region_type.value if hasattr(region.region_type, "value") else str(region.region_type)
    preferred = _DEFAULT_BY_REGION.get(rtype, _DEFAULT_BY_REGION["other"])
    candidates = [m for m in catalog if _suited(m, rtype)]
    if not candidates:
        candidates = list(catalog)
    for pref in preferred:
        for m in candidates:
            mt = m.material_type.value if hasattr(m.material_type, "value") else str(m.material_type)
            if mt == pref:
                return m, f"Catalog match for {rtype.replace('_', ' ')} ({pref.replace('_', ' ')})"
    if candidates:
        return candidates[0], f"Best available catalog option for {rtype.replace('_', ' ')}"
    return None, "No catalog materials available"


def _gemini_suggest(
    image_path: Path | None,
    regions: list[StructureRegion],
    catalog: list[Material],
) -> dict[int, tuple[int, str]] | None:
    """Return {region_id: (material_id, reason)} or None on failure."""
    if not regions or not catalog:
        return None

    region_payload = []
    for r in regions:
        rtype = r.region_type.value if hasattr(r.region_type, "value") else str(r.region_type)
        region_payload.append({"region_id": r.id, "region_type": rtype, "label": r.label or rtype})

    mat_payload = []
    for m in catalog:
        mt = m.material_type.value if hasattr(m.material_type, "value") else str(m.material_type)
        mat_payload.append(
            {
                "material_id": m.id,
                "name": m.name,
                "material_type": mt,
                "suitable_regions": list(m.suitable_regions or []),
                "rate": float(m.material_rate or 0),
                "unit": m.unit,
            }
        )

    prompt = (
        "You are an exterior renovation consultant looking at this house photo. "
        "Suggest ONE catalog material per detected region for a cohesive, climate-sensible facade redesign.\n"
        "Prefer the same wall-finish family across main_wall / parapet / pillar when suitable.\n"
        "Windows: frame/trim-friendly finishes only. Gates: durable metal/composite. "
        "Roof edge: cladding or trim — not random paint.\n"
        "Return ONLY a JSON array:\n"
        '[{"region_id": number, "material_id": number, "reason": "short why"}]\n'
        "Use only material_id values from the catalog. One suggestion per region_id. "
        "Prefer materials whose suitable_regions include the region type.\n\n"
        f"REGIONS:\n{json.dumps(region_payload)}\n\n"
        f"CATALOG:\n{json.dumps(mat_payload)}"
    )

    data = gemini_vision_json(prompt, image_path, temperature=0.25)
    if data is None:
        return None
    if isinstance(data, dict):
        data = data.get("suggestions") or data.get("items") or []
    if not isinstance(data, list):
        return None

    valid_mats = {m.id for m in catalog}
    valid_regs = {r.id for r in regions}
    out: dict[int, tuple[int, str]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            rid = int(item.get("region_id"))
            mid = int(item.get("material_id"))
        except (TypeError, ValueError):
            continue
        if rid not in valid_regs or mid not in valid_mats:
            continue
        reason = str(item.get("reason") or "AI suggestion").strip()[:180]
        out[rid] = (mid, reason or "AI suggestion")
    if out:
        logger.info("MATERIAL suggest gemini regions=%s", len(out))
    return out or None


def suggest_materials_for_project(db: Session, project_id: int) -> list[dict]:
    """
    Suggest a material for each structure region on the project.
    Returns list of {region_id, material_id, reason, source, material_name, region_label}.
    """
    regions = (
        db.query(StructureRegion)
        .filter(StructureRegion.project_id == project_id)
        .order_by(StructureRegion.id)
        .all()
    )
    catalog = _catalog_materials(db)
    if not regions or not catalog:
        return []

    primary = (
        db.query(ProjectImage)
        .filter(ProjectImage.project_id == project_id, ProjectImage.is_primary.is_(True))
        .first()
    )
    if primary is None:
        primary = db.query(ProjectImage).filter(ProjectImage.project_id == project_id).first()

    image_path: Path | None = None
    if primary:
        from app.services.storage import absolute_path

        image_path = absolute_path(primary.file_path)

    ai_map = _gemini_suggest(image_path, regions, catalog)
    source = "gemini" if ai_map else "rules"
    if not ai_map:
        logger.info("MATERIAL suggest using rule-based fallback (set a valid GEMINI_API_KEY for AI)")

    mat_by_id = {m.id: m for m in catalog}
    results: list[dict] = []
    for r in regions:
        rtype = r.region_type.value if hasattr(r.region_type, "value") else str(r.region_type)
        used_ai = False
        if ai_map and r.id in ai_map:
            mid, reason = ai_map[r.id]
            mat = mat_by_id.get(mid)
            if mat and not _suited(mat, rtype):
                alt, alt_reason = _rule_pick(r, catalog)
                if alt:
                    mat, reason, mid = alt, f"{reason} (adjusted to suited catalog)", alt.id
            used_ai = mat is not None
        else:
            mat, reason = _rule_pick(r, catalog)
            mid = mat.id if mat else None
        if not mat or mid is None:
            continue
        results.append(
            {
                "region_id": r.id,
                "region_label": r.label or rtype.replace("_", " ").title(),
                "region_type": rtype,
                "material_id": mid,
                "material_name": mat.name,
                "material_type": mat.material_type.value
                if hasattr(mat.material_type, "value")
                else str(mat.material_type),
                "reason": reason,
                "source": "gemini" if used_ai else ("rules" if not ai_map else "rules"),
            }
        )
    return results
