from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.api.projects import _get_project_or_404
from app.core.database import get_db
from app.models import ProjectImage, User
from app.schemas import ImageOut
from app.services.gemini import gemini_quality_notes
from app.services.quality import check_image_quality
from app.services.storage import absolute_path, save_upload

router = APIRouter(prefix="/api/projects/{project_id}/images", tags=["images"])


@router.post("", response_model=ImageOut)
async def upload_image(
    project_id: int,
    file: UploadFile = File(...),
    user: User = Depends(require_permission("project:edit")),
    db: Session = Depends(get_db),
):
    project = _get_project_or_404(db, project_id, user)
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads are allowed")

    rel, dest = save_upload(file, "originals")
    ok, message, w, h = check_image_quality(dest)
    gemini_note = await gemini_quality_notes(dest)
    if gemini_note:
        message = f"{message} {gemini_note}"

    # First image becomes primary
    existing = db.query(ProjectImage).filter(ProjectImage.project_id == project.id).count()
    image = ProjectImage(
        project_id=project.id,
        file_path=rel,
        original_filename=file.filename,
        is_primary=existing == 0,
        quality_ok=ok,
        quality_message=message,
        width_px=w,
        height_px=h,
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    if not ok:
        # Still saved so user can see guidance; client should block continue
        pass
    return image


@router.get("", response_model=list[ImageOut])
def list_images(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id, user)
    return db.query(ProjectImage).filter(ProjectImage.project_id == project.id).all()


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
