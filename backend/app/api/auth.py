from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, require_permission
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models import Role, User, UserRole
from app.schemas import AssignRoleIn, PasswordChange, Token, UserCreate, UserOut, UserUpdate
from app.services.storage import absolute_path, save_upload

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        company=user.company,
        logo_path=user.logo_path,
        is_active=user.is_active,
        roles=[ur.role for ur in user.roles],
        created_at=user.created_at,
    )


@router.post("/register", response_model=UserOut)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email.lower()).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    role = db.query(Role).filter(Role.name == payload.role).first()
    if not role:
        raise HTTPException(status_code=400, detail="Role not found. Run seed first.")
    user = User(
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        phone=payload.phone,
        company=payload.company,
    )
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.commit()
    user = (
        db.query(User)
        .options(joinedload(User.roles).joinedload(UserRole.role))
        .filter(User.id == user.id)
        .first()
    )
    return _user_out(user)


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username.lower()).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    token = create_access_token(str(user.id))
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return _user_out(user)


@router.patch("/me", response_model=UserOut)
def update_me(payload: UserUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.phone is not None:
        user.phone = payload.phone
    if payload.company is not None:
        user.company = payload.company
    db.commit()
    user = (
        db.query(User)
        .options(joinedload(User.roles).joinedload(UserRole.role))
        .filter(User.id == user.id)
        .first()
    )
    return _user_out(user)


@router.post("/me/password")
def change_password(
    payload: PasswordChange,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must be different")
    user.hashed_password = hash_password(payload.new_password)
    db.commit()
    return {"ok": True, "detail": "Password updated"}


@router.post("/me/logo", response_model=UserOut)
async def upload_logo(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image logos are allowed")
    rel, _ = save_upload(file, "logos")
    user.logo_path = rel
    db.commit()
    user = (
        db.query(User)
        .options(joinedload(User.roles).joinedload(UserRole.role))
        .filter(User.id == user.id)
        .first()
    )
    return _user_out(user)


@router.get("/me/logo")
def get_my_logo(user: User = Depends(get_current_user)):
    if not user.logo_path:
        raise HTTPException(status_code=404, detail="No logo uploaded")
    path = absolute_path(user.logo_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Logo file missing")
    return FileResponse(path)


@router.post("/users/{user_id}/roles", response_model=UserOut)
def assign_role(
    user_id: int,
    payload: AssignRoleIn,
    _: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    target = (
        db.query(User)
        .options(joinedload(User.roles).joinedload(UserRole.role))
        .filter(User.id == user_id)
        .first()
    )
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    role = db.query(Role).filter(Role.name == payload.role).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    existing = {ur.role_id for ur in target.roles}
    if role.id not in existing:
        db.add(UserRole(user_id=target.id, role_id=role.id))
        db.commit()
        target = (
            db.query(User)
            .options(joinedload(User.roles).joinedload(UserRole.role))
            .filter(User.id == user_id)
            .first()
        )
    return _user_out(target)


@router.get("/users", response_model=list[UserOut])
def list_users(
    _: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    users = db.query(User).options(joinedload(User.roles).joinedload(UserRole.role)).all()
    return [_user_out(u) for u in users]
