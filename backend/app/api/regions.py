from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import logging

from app.api.deps import get_current_user, require_permission
from app.api.projects import _get_project_for_edit, _get_project_or_404
from app.core.config import get_settings
from app.core.database import get_db
from app.models import ProjectImage, RegionType, StructureRegion, User
from app.schemas import DetectRegionsResponse, RegionCreate, RegionOut, RegionUpdate
from app.services.gemini import detect_structure_regions
from app.services.segformer import StructureDetectError
from app.services.storage import absolute_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/regions", tags=["regions"])

_ENGINE_LABELS = {
    "gemini": "Gemini vision",
    "segformer": "SegFormer",
    "grounded_sam": "Grounded-SAM",
    "opencv": "OpenCV",
    "unknown": "Auto-detect",
}


@router.post("/detect", response_model=DetectRegionsResponse)
async def detect_regions(
    project_id: int,
    user: User = Depends(require_permission("regions:edit")),
    db: Session = Depends(get_db),
):
    project = _get_project_for_edit(db, project_id, user)
    image = (
        db.query(ProjectImage)
        .filter(ProjectImage.project_id == project.id, ProjectImage.is_primary.is_(True))
        .first()
    )
    if not image:
        image = db.query(ProjectImage).filter(ProjectImage.project_id == project.id).first()
    if not image:
        raise HTTPException(status_code=400, detail="Upload an exterior image first")

    try:
        detected, meta = await detect_structure_regions(absolute_path(image.file_path))
    except StructureDetectError as exc:
        logger.error("Region detect 503 for project %s: %s", project_id, exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Region detect unexpected error for project %s", project_id)
        raise HTTPException(status_code=503, detail=f"Detection failed: {exc}") from exc
    if not detected:
        raise HTTPException(
            status_code=422,
            detail="No structure regions found. Try a clearer front view, or draw regions manually.",
        )

    # Keep manually corrected regions; only wipe auto-detected ones
    db.query(StructureRegion).filter(
        StructureRegion.project_id == project.id,
        StructureRegion.user_corrected.is_(False),
    ).delete()
    created = []
    for item in detected:
        region = StructureRegion(
            project_id=project.id,
            region_type=RegionType(item["region_type"]),
            label=item.get("label"),
            points=item.get("points") or [],
            confidence=item.get("confidence"),
            user_corrected=False,
        )
        db.add(region)
        created.append(region)
    db.commit()
    for r in created:
        db.refresh(r)

    engine = (meta or {}).get("primary") or "unknown"
    used = list((meta or {}).get("engines_used") or [])
    nice = _ENGINE_LABELS.get(engine, engine)
    used_nice = ", ".join(_ENGINE_LABELS.get(e, e) for e in used) if used else nice
    message = f"{nice} detected {len(created)} regions"
    if len(used) > 1:
        message += f" (pipeline: {used_nice})"
    gemini_note = (meta or {}).get("gemini_note")
    if engine == "opencv" and gemini_note:
        # Keep toast readable; full reason already in gemini_note
        short = gemini_note if len(gemini_note) <= 160 else gemini_note[:157] + "…"
        message += f" — {short}"
    elif engine == "opencv" and not (get_settings().gemini_api_key or "").strip():
        message += " — set GEMINI_API_KEY (AI Studio AIza… key) on the server"
    message += ". Drag handles to fine-tune."

    return DetectRegionsResponse(
        regions=created,
        engine=engine,
        engines_used=used,
        message=message,
    )


@router.get("", response_model=list[RegionOut])
def list_regions(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id, user)
    return db.query(StructureRegion).filter(StructureRegion.project_id == project.id).all()


@router.post("", response_model=RegionOut)
def create_region(
    project_id: int,
    payload: RegionCreate,
    user: User = Depends(require_permission("regions:edit")),
    db: Session = Depends(get_db),
):
    project = _get_project_for_edit(db, project_id, user)
    region = StructureRegion(
        project_id=project.id,
        region_type=payload.region_type,
        label=payload.label,
        points=[p.model_dump() for p in payload.points],
        confidence=payload.confidence,
        user_corrected=payload.user_corrected,
    )
    db.add(region)
    db.commit()
    db.refresh(region)
    return region


@router.patch("/{region_id}", response_model=RegionOut)
def update_region(
    project_id: int,
    region_id: int,
    payload: RegionUpdate,
    user: User = Depends(require_permission("regions:edit")),
    db: Session = Depends(get_db),
):
    project = _get_project_for_edit(db, project_id, user)
    region = (
        db.query(StructureRegion)
        .filter(StructureRegion.id == region_id, StructureRegion.project_id == project.id)
        .first()
    )
    if not region:
        raise HTTPException(status_code=404, detail="Region not found")
    if payload.region_type is not None:
        region.region_type = payload.region_type
    if payload.label is not None:
        region.label = payload.label
    if payload.points is not None:
        region.points = [p.model_dump() for p in payload.points]
    if payload.user_corrected is not None:
        region.user_corrected = payload.user_corrected
    db.commit()
    db.refresh(region)
    return region


@router.delete("/all")
def clear_regions(
    project_id: int,
    user: User = Depends(require_permission("regions:edit")),
    db: Session = Depends(get_db),
):
    """Remove all structure regions for this project (design material links cascade)."""
    project = _get_project_for_edit(db, project_id, user)
    deleted = (
        db.query(StructureRegion)
        .filter(StructureRegion.project_id == project.id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"ok": True, "deleted": int(deleted or 0)}


@router.delete("/{region_id}")
def delete_region(
    project_id: int,
    region_id: int,
    user: User = Depends(require_permission("regions:edit")),
    db: Session = Depends(get_db),
):
    project = _get_project_for_edit(db, project_id, user)
    region = (
        db.query(StructureRegion)
        .filter(StructureRegion.id == region_id, StructureRegion.project_id == project.id)
        .first()
    )
    if not region:
        raise HTTPException(status_code=404, detail="Region not found")
    db.delete(region)
    db.commit()
    return {"ok": True}
