from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.api.projects import _get_project_for_edit, _get_project_or_404
from app.core.database import get_db
from app.models import AreaEstimate, ProjectImage, QuantityLine, RateOverride, RegionType, User
from app.schemas import (
    AreaEstimateOut,
    AreaOverrideIn,
    CostLineOut,
    CostSummaryOut,
    QuantityLineOut,
    QuantityOverrideIn,
    RateOverrideIn,
    ReferenceMeasurements,
)
from app.services.estimation import calculate_quantities_and_costs, estimate_areas
from app.services.storage import absolute_path

router = APIRouter(prefix="/api/projects/{project_id}/estimation", tags=["estimation"])


@router.post("/areas", response_model=list[AreaEstimateOut])
async def run_area_estimation(
    project_id: int,
    refs: ReferenceMeasurements | None = None,
    user: User = Depends(require_permission("project:edit")),
    db: Session = Depends(get_db),
):
    project = _get_project_for_edit(db, project_id, user)
    image = (
        db.query(ProjectImage)
        .filter(ProjectImage.project_id == project.id, ProjectImage.is_primary.is_(True))
        .first()
    )
    refs = refs or ReferenceMeasurements()
    depth_info = None
    # Skip slow HF/Replicate depth when the user already provided facade size
    has_refs = bool(refs.known_width_ft and refs.known_height_ft)
    if image is not None and not has_refs:
        from app.services.depth_scale import refine_facade_scale

        depth_info = await refine_facade_scale(
            absolute_path(image.file_path),
            image_width=image.width_px,
            image_height=image.height_px,
            known_width_ft=refs.known_width_ft,
            known_height_ft=refs.known_height_ft,
        )
    elif image is not None and has_refs:
        from app.services.depth_scale import DepthScaleInfo

        depth_info = DepthScaleInfo(
            facade_width_ft=float(refs.known_width_ft),
            facade_height_ft=float(refs.known_height_ft),
            depth_map=None,
            method="user_reference",
            confidence=0.95,
        )
    return estimate_areas(
        db,
        project,
        image.width_px if image else None,
        image.height_px if image else None,
        known_width_ft=refs.known_width_ft,
        known_height_ft=refs.known_height_ft,
        depth_info=depth_info,
    )


@router.get("/areas", response_model=list[AreaEstimateOut])
def list_areas(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id, user)
    return db.query(AreaEstimate).filter(AreaEstimate.project_id == project.id).all()


@router.post("/areas/override", response_model=AreaEstimateOut)
def override_area(
    project_id: int,
    payload: AreaOverrideIn,
    user: User = Depends(require_permission("areas:override")),
    db: Session = Depends(get_db),
):
    project = _get_project_for_edit(db, project_id, user)
    existing = (
        db.query(AreaEstimate)
        .filter(
            AreaEstimate.project_id == project.id,
            AreaEstimate.region_id == payload.region_id,
            AreaEstimate.user_override.is_(True),
        )
        .first()
    )
    if existing:
        existing.region_type = payload.region_type
        existing.area_sq_ft = payload.area_sq_ft
        existing.length_ft = payload.length_ft
        existing.notes = payload.notes
        existing.method = "user_override"
        existing.confidence = 1.0
        db.commit()
        db.refresh(existing)
        return existing
    est = AreaEstimate(
        project_id=project.id,
        region_id=payload.region_id,
        region_type=payload.region_type,
        area_sq_ft=payload.area_sq_ft,
        length_ft=payload.length_ft,
        method="user_override",
        confidence=1.0,
        user_override=True,
        notes=payload.notes,
    )
    db.add(est)
    db.commit()
    db.refresh(est)
    return est


@router.post("/calculate", response_model=CostSummaryOut)
def calculate(
    project_id: int,
    user: User = Depends(require_permission("project:edit")),
    db: Session = Depends(get_db),
):
    project = _get_project_for_edit(db, project_id, user)
    result = calculate_quantities_and_costs(db, project)
    return CostSummaryOut(
        lines=result["costs"],
        material_total=result["material_total"],
        labor_total=result["labor_total"],
        grand_total=result["grand_total"],
    )


@router.get("/quantities", response_model=list[QuantityLineOut])
def list_quantities(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id, user)
    return db.query(QuantityLine).filter(QuantityLine.project_id == project.id).all()


@router.post("/quantities/override", response_model=QuantityLineOut)
def override_quantity(
    project_id: int,
    payload: QuantityOverrideIn,
    user: User = Depends(require_permission("quantities:override")),
    db: Session = Depends(get_db),
):
    project = _get_project_for_edit(db, project_id, user)
    line = (
        db.query(QuantityLine)
        .filter(QuantityLine.id == payload.quantity_line_id, QuantityLine.project_id == project.id)
        .first()
    )
    if not line:
        raise HTTPException(status_code=404, detail="Quantity line not found")
    line.final_quantity = payload.final_quantity
    line.user_override = True
    db.commit()
    # Recalc costs with overrides preserved
    calculate_quantities_and_costs(db, project)
    db.refresh(line)
    return line


@router.post("/rates", response_model=CostSummaryOut)
def set_rates(
    project_id: int,
    payload: RateOverrideIn,
    user: User = Depends(require_permission("rates:edit")),
    db: Session = Depends(get_db),
):
    project = _get_project_for_edit(db, project_id, user)
    existing = (
        db.query(RateOverride)
        .filter(RateOverride.project_id == project.id, RateOverride.material_id == payload.material_id)
        .first()
    )
    if existing:
        if payload.material_rate is not None:
            existing.material_rate = payload.material_rate
        if payload.labor_rate is not None:
            existing.labor_rate = payload.labor_rate
    else:
        db.add(
            RateOverride(
                project_id=project.id,
                material_id=payload.material_id,
                material_rate=payload.material_rate,
                labor_rate=payload.labor_rate,
            )
        )
    db.commit()
    result = calculate_quantities_and_costs(db, project)
    return CostSummaryOut(
        lines=result["costs"],
        material_total=result["material_total"],
        labor_total=result["labor_total"],
        grand_total=result["grand_total"],
    )


@router.get("/costs", response_model=CostSummaryOut)
def get_costs(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models import CostLine

    project = _get_project_or_404(db, project_id, user)
    lines = db.query(CostLine).filter(CostLine.project_id == project.id).all()
    material_total = sum(l.material_cost for l in lines)
    labor_total = sum(l.labor_cost for l in lines)
    return CostSummaryOut(
        lines=lines,
        material_total=round(material_total, 2),
        labor_total=round(labor_total, 2),
        grand_total=round(material_total + labor_total, 2),
    )
