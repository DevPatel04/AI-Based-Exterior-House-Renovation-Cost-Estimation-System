from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import logging
import time

from app.api.deps import get_current_user, require_permission
from app.api.projects import _get_project_for_edit, _get_project_or_404
from app.core.database import get_db
from app.models import ProjectImage, RegionType, StructureRegion, User
from app.schemas import RegionCreate, RegionOut, RegionUpdate
from app.services.detect_log import format_summary
from app.services.gemini import detect_structure_regions
from app.services.segformer import StructureDetectError
from app.services.storage import absolute_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/regions", tags=["regions"])


@router.post("/detect", response_model=list[RegionOut])
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

    image_path = absolute_path(image.file_path)
    logger.info(
        "DETECT api start project=%s user=%s image_id=%s path=%s size=%sx%s",
        project_id,
        getattr(user, "id", None),
        image.id,
        image.file_path,
        image.width_px,
        image.height_px,
    )
    t0 = time.perf_counter()
    try:
        detected = await detect_structure_regions(image_path)
    except StructureDetectError as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        logger.error(
            "DETECT api 503 project=%s ms=%s err=%s",
            project_id,
            ms,
            exc,
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        logger.exception(
            "DETECT api unexpected project=%s ms=%s err=%s",
            project_id,
            ms,
            exc,
        )
        raise HTTPException(status_code=503, detail=f"Detection failed: {exc}") from exc
    if not detected:
        logger.warning("DETECT api empty project=%s", project_id)
        raise HTTPException(
            status_code=422,
            detail="No structure regions found. Try a clearer front view, or draw regions manually.",
        )

    # Keep manually corrected regions; only wipe auto-detected ones
    kept_manual = (
        db.query(StructureRegion)
        .filter(StructureRegion.project_id == project.id, StructureRegion.user_corrected.is_(True))
        .count()
    )
    deleted = (
        db.query(StructureRegion)
        .filter(StructureRegion.project_id == project.id, StructureRegion.user_corrected.is_(False))
        .delete()
    )
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
    ms = int((time.perf_counter() - t0) * 1000)
    logger.info(
        "DETECT api ok project=%s ms=%s wiped_auto=%s kept_manual=%s saved=%s %s",
        project_id,
        ms,
        deleted,
        kept_manual,
        len(created),
        format_summary(detected),
    )
    return created


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
