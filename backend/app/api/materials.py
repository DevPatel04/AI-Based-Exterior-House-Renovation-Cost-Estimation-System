from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.database import get_db
from app.models import Material, MaterialTexture, User
from app.schemas import MaterialCreate, MaterialOut, MaterialUpdate
from app.services.storage import absolute_path, save_upload

router = APIRouter(prefix="/api/materials", tags=["materials"])


class TextureOut(BaseModel):
    id: int
    material_id: int
    file_path: str
    label: str | None

    model_config = {"from_attributes": True}


@router.get("", response_model=list[MaterialOut])
def list_materials(
    include_inactive: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Material)
    if not include_inactive:
        q = q.filter(Material.is_active.is_(True), Material.approved.is_(True))
    return q.order_by(Material.material_type, Material.name).all()


@router.post("", response_model=MaterialOut)
def create_material(
    payload: MaterialCreate,
    user: User = Depends(require_permission("materials:manage")),
    db: Session = Depends(get_db),
):
    material = Material(
        **payload.model_dump(),
        created_by=user.id,
        approved=False,
    )
    from app.api.deps import get_user_role_names

    if "admin" in get_user_role_names(user):
        material.approved = True
    db.add(material)
    db.commit()
    db.refresh(material)
    return material


@router.patch("/{material_id}", response_model=MaterialOut)
def update_material(
    material_id: int,
    payload: MaterialUpdate,
    user: User = Depends(require_permission("materials:manage")),
    db: Session = Depends(get_db),
):
    material = db.get(Material, material_id)
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")
    data = payload.model_dump(exclude_unset=True)
    if "approved" in data:
        from app.api.deps import get_user_role_names

        if "admin" not in get_user_role_names(user):
            raise HTTPException(status_code=403, detail="Only admin can approve materials")
    for k, v in data.items():
        setattr(material, k, v)
    db.commit()
    db.refresh(material)
    return material


@router.post("/{material_id}/textures", response_model=TextureOut)
async def upload_texture(
    material_id: int,
    file: UploadFile = File(...),
    label: str | None = None,
    user: User = Depends(require_permission("materials:manage")),
    db: Session = Depends(get_db),
):
    material = db.get(Material, material_id)
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image textures allowed")
    rel, _ = save_upload(file, "textures")
    tex = MaterialTexture(material_id=material.id, file_path=rel, label=label or file.filename)
    db.add(tex)
    db.commit()
    db.refresh(tex)
    return tex


@router.get("/{material_id}/textures", response_model=list[TextureOut])
def list_textures(
    material_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(MaterialTexture).filter(MaterialTexture.material_id == material_id).all()


@router.get("/textures/{texture_id}/file")
def get_texture_file(
    texture_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tex = db.get(MaterialTexture, texture_id)
    if not tex:
        raise HTTPException(status_code=404, detail="Texture not found")
    path = absolute_path(tex.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing")
    return FileResponse(path)
