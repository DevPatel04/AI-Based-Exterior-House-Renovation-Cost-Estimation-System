from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_user_role_names, require_permission
from app.core.database import get_db
from app.core.permissions import user_has_permission
from app.models import Material, MaterialTexture, User
from app.schemas import MaterialCreate, MaterialOut, MaterialUpdate
from app.services.storage import absolute_path, save_image_upload, save_upload

router = APIRouter(prefix="/api/materials", tags=["materials"])


class TextureOut(BaseModel):
    id: int
    material_id: int
    file_path: str
    label: str | None

    model_config = {"from_attributes": True}


def _get_manageable_material(db: Session, material_id: int, user: User) -> Material:
    material = db.get(Material, material_id)
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")
    if "admin" not in get_user_role_names(user) and material.created_by != user.id:
        raise HTTPException(status_code=403, detail="You can only manage materials you created")
    return material


@router.get("", response_model=list[MaterialOut])
def list_materials(
    include_inactive: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    roles = get_user_role_names(user)
    can_manage = user_has_permission(roles, "materials:manage")
    q = db.query(Material)
    if include_inactive and can_manage:
        if "admin" in roles:
            return q.order_by(Material.material_type, Material.name).all()
        # Suppliers see approved catalog + their own (including pending)
        return (
            q.filter((Material.is_active.is_(True) & Material.approved.is_(True)) | (Material.created_by == user.id))
            .order_by(Material.material_type, Material.name)
            .all()
        )
    return (
        q.filter(Material.is_active.is_(True), Material.approved.is_(True))
        .order_by(Material.material_type, Material.name)
        .all()
    )


@router.post("", response_model=MaterialOut)
def create_material(
    payload: MaterialCreate,
    user: User = Depends(require_permission("materials:manage")),
    db: Session = Depends(get_db),
):
    material = Material(
        **payload.model_dump(),
        created_by=user.id,
        approved="admin" in get_user_role_names(user),
    )
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
    material = _get_manageable_material(db, material_id, user)
    data = payload.model_dump(exclude_unset=True)
    roles = get_user_role_names(user)
    if "approved" in data and "admin" not in roles:
        raise HTTPException(status_code=403, detail="Only admin can approve materials")
    rate_changed = any(k in data for k in ("material_rate", "labor_rate", "name", "coverage_per_unit", "wastage_percent"))
    for k, v in data.items():
        setattr(material, k, v)
    if rate_changed and "admin" not in roles and "approved" not in data:
        material.approved = False
    db.commit()
    db.refresh(material)
    return material


@router.post("/{material_id}/textures", response_model=TextureOut)
async def upload_texture(
    material_id: int,
    file: UploadFile = File(...),
    label: str | None = Form(None),
    user: User = Depends(require_permission("materials:manage")),
    db: Session = Depends(get_db),
):
    material = _get_manageable_material(db, material_id, user)
    try:
        rel, _ = await save_image_upload(file, "textures")
    except Exception:
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
