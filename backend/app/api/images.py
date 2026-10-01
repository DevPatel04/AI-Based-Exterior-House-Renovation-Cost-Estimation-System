from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.api.projects import _get_project_for_edit, _get_project_or_404
from app.core.config import get_settings
from app.core.database import get_db
from app.models import ProjectImage, User
from app.schemas import ImageOut
from app.services.quality import check_image_quality
from app.services.storage import absolute_path, save_image_upload

router = APIRouter(prefix="/api/projects/{project_id}/images", tags=["images"])


@router.post("", response_model=ImageOut)
async def upload_image(
    project_id: int,
    file: UploadFile = File(...),
    set_primary: str = Form("false"),
    user: User = Depends(require_permission("project:edit")),
    db: Session = Depends(get_db),
):
    project = _get_project_for_edit(db, project_id, user)
    # Any image format Pillow/OpenCV can handle; no MIME-type force
    rel, dest = await save_image_upload(file, "originals")
    ok, message, w, h = await run_in_threadpool(check_image_quality, dest)
    settings = get_settings()
    if settings.enable_gemini_quality_notes:
        from app.services.gemini import gemini_quality_notes

        gemini_note = await gemini_quality_notes(dest)
        if gemini_note:
            message = f"{message} {gemini_note}"

    existing = db.query(ProjectImage).filter(ProjectImage.project_id == project.id).count()
    make_primary = existing == 0 or set_primary.lower() in {"1", "true", "yes", "on"}
    if make_primary and existing > 0:
        db.query(ProjectImage).filter(ProjectImage.project_id == project.id).update({"is_primary": False})

    image = ProjectImage(
        project_id=project.id,
        file_path=rel,
        original_filename=file.filename,
        is_primary=make_primary,
        quality_ok=ok,
        quality_message=message,
        width_px=w,
        height_px=h,
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    return image


@router.post("/{image_id}/set-primary", response_model=ImageOut)
def set_primary_image(
    project_id: int,
    image_id: int,
    user: User = Depends(require_permission("project:edit")),
    db: Session = Depends(get_db),
):
    project = _get_project_for_edit(db, project_id, user)
    image = (
        db.query(ProjectImage)
        .filter(ProjectImage.id == image_id, ProjectImage.project_id == project.id)
        .first()
    )
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    db.query(ProjectImage).filter(ProjectImage.project_id == project.id).update({"is_primary": False})
    image.is_primary = True
    db.commit()
    db.refresh(image)
    return image


@router.get("", response_model=list[ImageOut])
def list_images(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id, user)
    return db.query(ProjectImage).filter(ProjectImage.project_id == project.id).order_by(ProjectImage.id).all()


@router.get("/{image_id}/file")
def get_image_file(
    project_id: int,
    image_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _get_project_or_404(db, project_id, user)
    image = db.query(ProjectImage).filter(ProjectImage.id == image_id, ProjectImage.project_id == project.id).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    path = absolute_path(image.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(path)
