from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.api.projects import _get_project_or_404
from app.core.database import get_db
from app.models import Design, Report, User
from app.schemas import ReportOut
from app.services.report import generate_project_report
from app.services.storage import absolute_path

router = APIRouter(prefix="/api/projects/{project_id}/reports", tags=["reports"])


@router.post("", response_model=ReportOut)
def create_report(
    project_id: int,
    design_id: int | None = None,
    user: User = Depends(require_permission("report:download")),
    db: Session = Depends(get_db),
):
    project = _get_project_or_404(db, project_id, user)
    design = None
    if design_id is not None:
        design = db.query(Design).filter(Design.id == design_id, Design.project_id == project.id).first()
        if not design:
            raise HTTPException(status_code=404, detail="Design not found")
    report = generate_project_report(db, project, design, branding_user=user)
    return report


@router.get("", response_model=list[ReportOut])
def list_reports(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id, user)
    return db.query(Report).filter(Report.project_id == project.id).order_by(Report.created_at.desc()).all()


@router.get("/{report_id}/download")
def download_report(
    project_id: int,
    report_id: int,
    user: User = Depends(require_permission("report:download")),
    db: Session = Depends(get_db),
):
    project = _get_project_or_404(db, project_id, user)
    report = db.query(Report).filter(Report.id == report_id, Report.project_id == project.id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    path = absolute_path(report.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing")
    return FileResponse(path, filename=f"renovation-report-{project.id}.pdf", media_type="application/pdf")
