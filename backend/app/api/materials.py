from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.database import get_db
from app.models import Material, User
from app.schemas import MaterialCreate, MaterialOut, MaterialUpdate

router = APIRouter(prefix="/api/materials", tags=["materials"])


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
        approved=False,  # admin approves supplier submissions; admin creator can approve via patch
    )
    # Admin-created materials auto-approve
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
