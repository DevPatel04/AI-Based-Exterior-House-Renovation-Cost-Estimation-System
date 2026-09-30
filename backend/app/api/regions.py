from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.api.projects import _get_project_for_edit, _get_project_or_404
from app.core.database import get_db
from app.models import ProjectImage, RegionType, StructureRegion, User
from app.schemas import RegionCreate, RegionOut, RegionUpdate
from app.services.gemini import detect_structure_regions
from app.services.storage import absolute_path

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

    detected = await detect_structure_regions(absolute_path(image.file_path))
    db.query(StructureRegion).filter(StructureRegion.project_id == project.id).delete()
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
