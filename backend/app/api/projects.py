from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, get_user_role_names, require_permission
from app.core.database import get_db
from app.core.permissions import user_has_permission
from app.models import MemberRole, Project, ProjectMember, ProjectStatus, User
from app.schemas import ProjectCreate, ProjectMemberIn, ProjectMemberOut, ProjectOut, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _can_access(db: Session, project: Project, user: User) -> bool:
    if project.owner_id == user.id:
        return True
    roles = get_user_role_names(user)
    if "admin" in roles:
        return True
    member = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)
        .first()
    )
    return member is not None


def _get_project_or_404(db: Session, project_id: int, user: User) -> Project:
    project = db.get(Project, project_id)
    if not project or project.is_archived:
        raise HTTPException(status_code=404, detail="Project not found")
    if not _can_access(db, project, user):
        raise HTTPException(status_code=403, detail="No access to this project")
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    roles = get_user_role_names(user)
    if "admin" in roles:
        return db.query(Project).filter(Project.is_archived.is_(False)).order_by(Project.updated_at.desc()).all()
    owned = db.query(Project).filter(Project.owner_id == user.id, Project.is_archived.is_(False))
    shared_ids = [
        m.project_id
        for m in db.query(ProjectMember).filter(ProjectMember.user_id == user.id).all()
    ]
    shared = db.query(Project).filter(Project.id.in_(shared_ids), Project.is_archived.is_(False)) if shared_ids else []
    projects = {p.id: p for p in list(owned) + list(shared)}
    return sorted(projects.values(), key=lambda p: p.updated_at, reverse=True)


@router.post("", response_model=ProjectOut)
def create_project(
    payload: ProjectCreate,
    user: User = Depends(require_permission("project:create")),
    db: Session = Depends(get_db),
):
    project = Project(
        title=payload.title,
        description=payload.description,
        status=ProjectStatus.draft,
        owner_id=user.id,
    )
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, member_role=MemberRole.owner))
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _get_project_or_404(db, project_id, user)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    user: User = Depends(require_permission("project:edit")),
    db: Session = Depends(get_db),
):
    project = _get_project_or_404(db, project_id, user)
    if payload.title is not None:
        project.title = payload.title
    if payload.description is not None:
        project.description = payload.description
    if payload.status is not None:
        project.status = payload.status
    if payload.is_archived is not None:
        project.is_archived = payload.is_archived
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}")
def archive_project(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _get_project_or_404(db, project_id, user)
    if project.owner_id != user.id and "admin" not in get_user_role_names(user):
        raise HTTPException(status_code=403, detail="Only owner/admin can archive")
    project.is_archived = True
    db.commit()
    return {"ok": True}


@router.post("/{project_id}/members", response_model=ProjectMemberOut)
def share_project(
    project_id: int,
    payload: ProjectMemberIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _get_project_or_404(db, project_id, user)
    if project.owner_id != user.id and "admin" not in get_user_role_names(user):
        raise HTTPException(status_code=403, detail="Only owner/admin can share")
    target = db.query(User).filter(User.email == payload.user_email.lower()).first()
    if not target:
        raise HTTPException(status_code=404, detail="User email not found")
    existing = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project.id, ProjectMember.user_id == target.id)
        .first()
    )
    if existing:
        existing.member_role = payload.member_role
        db.commit()
        db.refresh(existing)
        return ProjectMemberOut(
            id=existing.id,
            user_id=target.id,
            member_role=existing.member_role,
            email=target.email,
            full_name=target.full_name,
        )
    member = ProjectMember(project_id=project.id, user_id=target.id, member_role=payload.member_role)
    db.add(member)
    db.commit()
    db.refresh(member)
    return ProjectMemberOut(
        id=member.id,
        user_id=target.id,
        member_role=member.member_role,
        email=target.email,
        full_name=target.full_name,
    )


@router.get("/{project_id}/members", response_model=list[ProjectMemberOut])
def list_members(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id, user)
    members = (
        db.query(ProjectMember)
        .options(joinedload(ProjectMember.user))
        .filter(ProjectMember.project_id == project.id)
        .all()
    )
    return [
        ProjectMemberOut(
            id=m.id,
            user_id=m.user_id,
            member_role=m.member_role,
            email=m.user.email if m.user else None,
            full_name=m.user.full_name if m.user else None,
        )
        for m in members
    ]
