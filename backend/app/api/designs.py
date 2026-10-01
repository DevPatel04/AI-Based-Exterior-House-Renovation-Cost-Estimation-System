from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.api.projects import _get_project_for_edit, _get_project_or_404
from app.core.database import get_db
from app.models import Design, DesignRegionMaterial, Material, ProjectImage, ProjectStatus, StructureRegion, User
from app.schemas import DesignCreate, DesignOut, DesignRegionMaterialIn, VisualizeRequest
from app.services.cloudflare import generate_redesign
from app.services.gemini import build_redesign_prompt
from app.services.storage import absolute_path

router = APIRouter(prefix="/api/projects/{project_id}/designs", tags=["designs"])


@router.get("", response_model=list[DesignOut])
def list_designs(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id, user)
    return db.query(Design).filter(Design.project_id == project.id).order_by(Design.created_at.desc()).all()


@router.post("", response_model=DesignOut)
def create_design(
    project_id: int,
    payload: DesignCreate,
    user: User = Depends(require_permission("materials:select")),
    db: Session = Depends(get_db),
):
    project = _get_project_for_edit(db, project_id, user)
    design = Design(project_id=project.id, name=payload.name.strip() or "Design", is_active=False)
    db.add(design)
    db.commit()
    db.refresh(design)
    return design


@router.post("/{design_id}/activate", response_model=DesignOut)
def activate_design(
    project_id: int,
    design_id: int,
    user: User = Depends(require_permission("materials:select")),
    db: Session = Depends(get_db),
):
    project = _get_project_for_edit(db, project_id, user)
    design = db.query(Design).filter(Design.id == design_id, Design.project_id == project.id).first()
    if not design:
        raise HTTPException(status_code=404, detail="Design not found")
    db.query(Design).filter(Design.project_id == project.id).update({"is_active": False})
    design.is_active = True
    project.status = ProjectStatus.designed
    db.commit()
    db.refresh(design)
    return design


@router.post("/{design_id}/materials", response_model=DesignOut)
def assign_materials(
    project_id: int,
    design_id: int,
    items: list[DesignRegionMaterialIn],
    user: User = Depends(require_permission("materials:select")),
    db: Session = Depends(get_db),
):
    project = _get_project_for_edit(db, project_id, user)
    design = db.query(Design).filter(Design.id == design_id, Design.project_id == project.id).first()
    if not design:
        raise HTTPException(status_code=404, detail="Design not found")

    # Replace semantics: clear previous mappings, then write the submitted set
    valid_items = [i for i in items if i.material_id and i.material_id > 0 and i.region_id > 0]
    db.query(DesignRegionMaterial).filter(DesignRegionMaterial.design_id == design.id).delete()
    db.flush()

    for item in valid_items:
        region = (
            db.query(StructureRegion)
            .filter(StructureRegion.id == item.region_id, StructureRegion.project_id == project.id)
            .first()
        )
        material = db.get(Material, item.material_id)
        if not region and not material:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid region and material: region_id={item.region_id} is not on this project "
                    f"(re-detect may have replaced it), and material_id={item.material_id} was not found."
                ),
            )
        if not region:
            alive = [
                rid
                for (rid,) in db.query(StructureRegion.id)
                .filter(StructureRegion.project_id == project.id)
                .all()
            ]
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid region (not material): region_id={item.region_id} is not on this project. "
                    f"Current region ids: {alive or 'none'}. "
                    "Re-detect replaces auto regions — re-select materials on current regions."
                ),
            )
        if not material:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid material (not region): material_id={item.material_id} was not found "
                    f"(for region_id={item.region_id}). Deleted or never seeded — pick another from the catalog."
                ),
            )
        if not material.is_active:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid material: “{material.name}” (id={material.id}) is inactive. "
                    "Choose an active material."
                ),
            )
        db.add(
            DesignRegionMaterial(
                design_id=design.id, region_id=item.region_id, material_id=item.material_id
            )
        )
    db.commit()
    db.refresh(design)
    return design


@router.get("/{design_id}/materials")
def get_design_materials(
    project_id: int,
    design_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _get_project_or_404(db, project_id, user)
    design = db.query(Design).filter(Design.id == design_id, Design.project_id == project.id).first()
    if not design:
        raise HTTPException(status_code=404, detail="Design not found")
    rows = db.query(DesignRegionMaterial).filter(DesignRegionMaterial.design_id == design.id).all()
    return [{"region_id": r.region_id, "material_id": r.material_id} for r in rows]


@router.post("/visualize", response_model=DesignOut)
async def visualize(
    project_id: int,
    payload: VisualizeRequest,
    user: User = Depends(require_permission("visualize:generate")),
    db: Session = Depends(get_db),
):
    project = _get_project_for_edit(db, project_id, user)
    design = db.query(Design).filter(Design.id == payload.design_id, Design.project_id == project.id).first()
    if not design:
        raise HTTPException(status_code=404, detail="Design not found")

    image = (
        db.query(ProjectImage)
        .filter(ProjectImage.project_id == project.id, ProjectImage.is_primary.is_(True))
        .first()
    )
    if not image:
        image = db.query(ProjectImage).filter(ProjectImage.project_id == project.id).first()
    if not image:
        raise HTTPException(status_code=400, detail="Upload an image first")

    mappings = db.query(DesignRegionMaterial).filter(DesignRegionMaterial.design_id == design.id).all()
    if not mappings:
        raise HTTPException(
            status_code=400,
            detail=f"Assign materials to “{design.name}” and save before generating a redesign",
        )
    parts = []
    for m in mappings:
        mat = db.get(Material, m.material_id)
        region = db.get(StructureRegion, m.region_id)
        if mat and region:
            parts.append(f"{mat.name} ({mat.material_type.value}) on {region.region_type.value}")
    # Include design name so local/AI prompts differ across variants even with similar materials
    prompt = build_redesign_prompt(
        f"Design variant “{design.name}”: " + ("; ".join(parts) if parts else "subtle modern exterior refresh")
    )
    rel, engine = await generate_redesign(absolute_path(image.file_path), prompt, hq_mode=payload.hq_mode)
    design.redesign_path = rel
    design.prompt_used = f"[{engine}] {prompt}"
    design.hq_mode = payload.hq_mode
    design.is_active = True
    db.query(Design).filter(Design.project_id == project.id, Design.id != design.id).update({"is_active": False})
    project.status = ProjectStatus.designed
    db.commit()
    db.refresh(design)
    return design


@router.get("/{design_id}/redesign")
def get_redesign_file(
    project_id: int,
    design_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _get_project_or_404(db, project_id, user)
    design = db.query(Design).filter(Design.id == design_id, Design.project_id == project.id).first()
    if not design or not design.redesign_path:
        raise HTTPException(status_code=404, detail="Redesign not found")
    path = absolute_path(design.redesign_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing")
    return FileResponse(path)
