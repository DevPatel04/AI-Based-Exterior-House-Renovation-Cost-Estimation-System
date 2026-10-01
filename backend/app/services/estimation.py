from pathlib import Path

from sqlalchemy.orm import Session

from app.models import (
    AreaEstimate,
    CostLine,
    Design,
    DesignRegionMaterial,
    Material,
    Project,
    ProjectImage,
    ProjectStatus,
    QuantityLine,
    RateOverride,
    RegionType,
    StructureRegion,
)
from app.services.depth_scale import DepthScaleInfo, region_depth_factor


def _polygon_area_norm(points: list[dict]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    for i in range(len(points)):
        j = (i + 1) % len(points)
        area += points[i]["x"] * points[j]["y"]
        area -= points[j]["x"] * points[i]["y"]
    return abs(area) / 2.0


def _min_norm_area(rtype: RegionType) -> float:
    if rtype == RegionType.window:
        return 0.004
    if rtype == RegionType.gate:
        return 0.006
    if rtype == RegionType.main_wall:
        return 0.05
    return 0.002


def estimate_areas(
    db: Session,
    project: Project,
    image_width: int | None,
    image_height: int | None,
    known_width_ft: float | None = None,
    known_height_ft: float | None = None,
    depth_info: DepthScaleInfo | None = None,
    ai_estimate: dict | None = None,
) -> list[AreaEstimate]:
    if ai_estimate is not None:
        facade_width_ft = float(ai_estimate["facade_width_ft"])
        facade_height_ft = float(ai_estimate["facade_height_ft"])
        base_method = str(ai_estimate.get("method") or "gemini_vision_qs")
        base_conf_boost = float(ai_estimate.get("confidence") or 0.7)
        ai_regions: dict[int, dict] = dict(ai_estimate.get("regions") or {})
    elif depth_info is not None:
        facade_width_ft = depth_info.facade_width_ft
        facade_height_ft = depth_info.facade_height_ft
        base_method = f"polygon_norm_x_{depth_info.method}"
        base_conf_boost = depth_info.confidence
        ai_regions = {}
    else:
        facade_width_ft = known_width_ft or 30.0
        facade_height_ft = known_height_ft or 22.0
        base_method = "polygon_norm_x_reference_facade"
        base_conf_boost = 0.5
        ai_regions = {}

    db.query(AreaEstimate).filter(
        AreaEstimate.project_id == project.id, AreaEstimate.user_override.is_(False)
    ).delete()
    db.flush()

    results: list[AreaEstimate] = []
    override_region_ids = {
        a.region_id
        for a in db.query(AreaEstimate)
        .filter(AreaEstimate.project_id == project.id, AreaEstimate.user_override.is_(True))
        .all()
        if a.region_id is not None
    }
    depth_map = depth_info.depth_map if depth_info else None

    for region in project.regions:
        if region.id in override_region_ids:
            continue

        ai_row = ai_regions.get(region.id)
        if ai_row is not None and not ai_row.get("include", True):
            # AI marked false detection — skip (no area line)
            continue

        norm_area = _polygon_area_norm(region.points or [])
        # Drop tiny noise polygons when not AI-approved
        if ai_row is None and norm_area < _min_norm_area(region.region_type):
            continue

        if ai_row is not None and ai_row.get("include", True):
            area_sq_ft = float(ai_row.get("area_sq_ft") or 0)
            length_ft = ai_row.get("length_ft")
            method = base_method
            conf = min(0.95, (float(region.confidence or 0.5) + base_conf_boost) / 2.0)
            note = (ai_row.get("note") or "").strip()
            if region.region_type == RegionType.main_wall:
                size_note = f"AI facade {facade_width_ft}×{facade_height_ft} ft"
                note = f"{size_note}. {note}".strip(". ")
        else:
            note = None
            depth_factor = region_depth_factor(depth_map, region.points or [])
            area_sq_ft = norm_area * facade_width_ft * facade_height_ft * depth_factor
            length_ft = None
            method = base_method
            if depth_factor != 1.0:
                method = f"{base_method}+depth_foreshorten"
            if region.region_type in {RegionType.railing, RegionType.roof_edge, RegionType.gate}:
                xs = [p["x"] for p in (region.points or [])]
                length_ft = (max(xs) - min(xs)) * facade_width_ft if xs else 0.0
                if region.region_type == RegionType.railing:
                    area_sq_ft = length_ft * 3.0
            conf = float(region.confidence or 0.5)
            if depth_info is not None:
                conf = min(0.95, (conf + base_conf_boost) / 2.0)

        # Final sanity: skip absurdly tiny computed areas
        if area_sq_ft < 1.0 and region.region_type in {RegionType.window, RegionType.gate}:
            continue

        est = AreaEstimate(
            project_id=project.id,
            region_id=region.id,
            region_type=region.region_type,
            area_sq_ft=round(float(area_sq_ft), 2),
            length_ft=round(float(length_ft), 2) if length_ft is not None else None,
            method=method,
            confidence=conf,
            user_override=False,
            notes=note,
        )
        db.add(est)
        results.append(est)

    # Store facade size as a project-level note on a synthetic row? Keep in first wall notes.
    db.commit()
    for r in results:
        db.refresh(r)
    return (
        db.query(AreaEstimate)
        .filter(AreaEstimate.project_id == project.id)
        .order_by(AreaEstimate.region_id, AreaEstimate.user_override.desc())
        .all()
    )


def calculate_quantities_and_costs(
    db: Session,
    project: Project,
    design: Design | None = None,
    *,
    image_path: Path | None = None,
    facade_width_ft: float | None = None,
    facade_height_ft: float | None = None,
    use_ai_quantities: bool = True,
) -> dict:
    if design is None:
        design = (
            db.query(Design)
            .filter(Design.project_id == project.id, Design.is_active.is_(True))
            .first()
        )
    if design is None:
        return {"quantities": [], "costs": [], "material_total": 0, "labor_total": 0, "grand_total": 0}

    kept_qty = {
        q.material_id: q
        for q in db.query(QuantityLine)
        .filter(QuantityLine.project_id == project.id, QuantityLine.user_override.is_(True))
        .all()
    }
    db.query(QuantityLine).filter(
        QuantityLine.project_id == project.id, QuantityLine.user_override.is_(False)
    ).delete()
    db.query(CostLine).filter(CostLine.project_id == project.id).delete()
    db.flush()

    overrides = {
        o.material_id: o
        for o in db.query(RateOverride).filter(RateOverride.project_id == project.id).all()
    }
    areas_by_region: dict[int, AreaEstimate] = {}
    for a in db.query(AreaEstimate).filter(AreaEstimate.project_id == project.id).all():
        if a.region_id is None:
            continue
        prev = areas_by_region.get(a.region_id)
        if prev is None or (a.user_override and not prev.user_override):
            areas_by_region[a.region_id] = a
        elif a.user_override == prev.user_override and a.id > prev.id:
            areas_by_region[a.region_id] = a

    # Aggregate by material (formula baseline)
    agg: dict[int, dict] = {}
    mappings = (
        db.query(DesignRegionMaterial)
        .filter(DesignRegionMaterial.design_id == design.id)
        .all()
    )
    areas_summary: list[dict] = []
    for m in mappings:
        material = db.get(Material, m.material_id)
        if not material:
            continue
        area = areas_by_region.get(m.region_id)
        qty_base = area.area_sq_ft if area else 0.0
        region = db.get(StructureRegion, m.region_id)
        rtype = (
            region.region_type.value
            if region and hasattr(region.region_type, "value")
            else (str(region.region_type) if region else "unknown")
        )
        areas_summary.append(
            {
                "region_id": m.region_id,
                "region_type": rtype,
                "area_sq_ft": qty_base,
                "length_ft": area.length_ft if area else None,
                "material_id": m.material_id,
                "material_name": material.name,
            }
        )
        if material.coverage_per_unit and material.coverage_per_unit > 0:
            if material.unit in {"liter", "litre", "bag", "piece", "panel"}:
                base = qty_base / material.coverage_per_unit
            else:
                base = qty_base
        else:
            base = qty_base

        if m.material_id not in agg:
            agg[m.material_id] = {
                "material": material,
                "base": 0.0,
                "category": material.material_type.value,
            }
        agg[m.material_id]["base"] += base

    # AI quantity override (preferred over pure coverage formula)
    ai_qty: dict[int, dict] | None = None
    if use_ai_quantities and agg:
        try:
            from app.services.ai_estimate import estimate_quantities_ai, material_catalog_row

            if image_path is None:
                primary = (
                    db.query(ProjectImage)
                    .filter(ProjectImage.project_id == project.id, ProjectImage.is_primary.is_(True))
                    .first()
                ) or db.query(ProjectImage).filter(ProjectImage.project_id == project.id).first()
                if primary:
                    from app.services.storage import absolute_path

                    image_path = absolute_path(primary.file_path)

            mats_payload = [material_catalog_row(data["material"]) for data in agg.values()]
            fw = facade_width_ft or 30.0
            fh = facade_height_ft or 22.0
            # Infer facade from largest wall area estimate if unknown
            if facade_width_ft is None:
                for a in areas_by_region.values():
                    if a.region_type == RegionType.main_wall and a.area_sq_ft > 50:
                        # rough: assume height 12 → width = area/height
                        fw = max(fw, round(float(a.area_sq_ft) / 12.0, 1))
                        break
            ai_qty = estimate_quantities_ai(image_path, mats_payload, areas_summary, fw, fh)
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning("AI quantities skipped: %s", exc)
            ai_qty = None

    qty_lines: list[QuantityLine] = []
    cost_lines: list[CostLine] = []
    material_total = 0.0
    labor_total = 0.0

    for mid, qline in list(kept_qty.items()):
        if mid not in agg:
            db.delete(qline)
            del kept_qty[mid]

    for mid, data in agg.items():
        material: Material = data["material"]
        if mid in kept_qty:
            qline = kept_qty[mid]
            qty_lines.append(qline)
            final_q = qline.final_quantity
        else:
            if ai_qty and mid in ai_qty:
                base = float(ai_qty[mid]["base_quantity"])
                wastage = float(ai_qty[mid]["wastage_percent"])
                unit = ai_qty[mid].get("unit") or material.unit
            else:
                wastage = material.wastage_percent
                base = round(data["base"], 3)
                unit = material.unit
            final_q = round(base * (1 + wastage / 100.0), 3)
            qline = QuantityLine(
                project_id=project.id,
                material_id=mid,
                category=data["category"],
                base_quantity=base,
                wastage_percent=wastage,
                final_quantity=final_q,
                unit=unit,
                user_override=False,
            )
            db.add(qline)
            qty_lines.append(qline)

        ov = overrides.get(mid)
        mat_rate = ov.material_rate if ov and ov.material_rate is not None else material.material_rate
        lab_rate = ov.labor_rate if ov and ov.labor_rate is not None else material.labor_rate
        mat_cost = round(final_q * mat_rate, 2)
        lab_cost = round(final_q * lab_rate, 2)
        total = round(mat_cost + lab_cost, 2)
        cline = CostLine(
            project_id=project.id,
            material_id=mid,
            category=data["category"],
            quantity=final_q,
            unit=qline.unit,
            material_rate=mat_rate,
            labor_rate=lab_rate,
            material_cost=mat_cost,
            labor_cost=lab_cost,
            total_cost=total,
        )
        db.add(cline)
        cost_lines.append(cline)
        material_total += mat_cost
        labor_total += lab_cost

    project.status = ProjectStatus.estimated
    db.commit()
    for q in qty_lines:
        db.refresh(q)
    for c in cost_lines:
        db.refresh(c)

    return {
        "quantities": qty_lines,
        "costs": cost_lines,
        "material_total": round(material_total, 2),
        "labor_total": round(labor_total, 2),
        "grand_total": round(material_total + labor_total, 2),
        "ai_quantities": bool(ai_qty),
    }
