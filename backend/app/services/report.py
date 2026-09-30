import uuid

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.models import (
    CostLine,
    Design,
    Material,
    Project,
    ProjectImage,
    ProjectStatus,
    QuantityLine,
    Report,
    User,
)
from app.services.storage import absolute_path, ensure_upload_dirs


def generate_project_report(
    db: Session,
    project: Project,
    design: Design | None = None,
    branding_user: User | None = None,
) -> Report:
    ensure_upload_dirs()
    if design is None:
        design = (
            db.query(Design)
            .filter(Design.project_id == project.id, Design.is_active.is_(True))
            .first()
        )

    primary = (
        db.query(ProjectImage)
        .filter(ProjectImage.project_id == project.id, ProjectImage.is_primary.is_(True))
        .first()
    )
    if primary is None:
        primary = db.query(ProjectImage).filter(ProjectImage.project_id == project.id).first()

    name = f"{uuid.uuid4().hex}.pdf"
    rel = f"reports/{name}"
    dest = absolute_path(rel)

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(dest), pagesize=A4)
    story = []

    brand_user = branding_user or db.get(User, project.owner_id)
    if brand_user and brand_user.logo_path:
        logo = absolute_path(brand_user.logo_path)
        if logo.exists():
            story.append(RLImage(str(logo), width=1.6 * inch, height=0.7 * inch, kind="proportional"))
            story.append(Spacer(1, 0.1 * inch))
            company = brand_user.company or brand_user.full_name
            story.append(Paragraph(f"<b>{company}</b>", styles["Normal"]))
            story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph("Exterior Renovation Planning Report", styles["Title"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(f"Project: <b>{project.title}</b>", styles["Normal"]))
    if project.description:
        story.append(Paragraph(project.description, styles["Normal"]))
    story.append(Spacer(1, 0.15 * inch))
    story.append(
        Paragraph(
            "<i>Advisory estimate only — not legally binding. For discussion with contractors.</i>",
            styles["Italic"],
        )
    )
    story.append(Spacer(1, 0.25 * inch))

    if primary:
        orig = absolute_path(primary.file_path)
        if orig.exists():
            story.append(Paragraph("Original exterior", styles["Heading2"]))
            story.append(RLImage(str(orig), width=5.5 * inch, height=3.5 * inch, kind="proportional"))
            story.append(Spacer(1, 0.2 * inch))

    if design and design.redesign_path:
        redes = absolute_path(design.redesign_path)
        if redes.exists():
            story.append(Paragraph(f"Redesign: {design.name}", styles["Heading2"]))
            story.append(RLImage(str(redes), width=5.5 * inch, height=3.5 * inch, kind="proportional"))
            story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("Selected materials", styles["Heading2"]))
    if design:
        from app.models import DesignRegionMaterial

        rows = [["Region ID", "Material", "Type"]]
        mappings = (
            db.query(DesignRegionMaterial)
            .filter(DesignRegionMaterial.design_id == design.id)
            .all()
        )
        for m in mappings:
            mat = db.get(Material, m.material_id)
            rows.append([str(m.region_id), mat.name if mat else "-", mat.material_type.value if mat else "-"])
        if len(rows) > 1:
            table = Table(rows, hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ]
                )
            )
            story.append(table)
        else:
            story.append(Paragraph("No materials assigned yet.", styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("Quantity calculations", styles["Heading2"]))
    qrows = [["Category", "Material ID", "Base", "Wastage %", "Final", "Unit"]]
    for q in db.query(QuantityLine).filter(QuantityLine.project_id == project.id).all():
        qrows.append(
            [
                q.category,
                str(q.material_id),
                str(q.base_quantity),
                str(q.wastage_percent),
                str(q.final_quantity),
                q.unit,
            ]
        )
    if len(qrows) > 1:
        qt = Table(qrows, hAlign="LEFT")
        qt.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ]
            )
        )
        story.append(qt)
    else:
        story.append(Paragraph("No quantities calculated yet.", styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("Cost breakdown", styles["Heading2"]))
    crows = [["Category", "Qty", "Mat. rate", "Labor rate", "Material", "Labor", "Total"]]
    mat_sum = lab_sum = grand = 0.0
    for c in db.query(CostLine).filter(CostLine.project_id == project.id).all():
        crows.append(
            [
                c.category,
                str(c.quantity),
                str(c.material_rate),
                str(c.labor_rate),
                str(c.material_cost),
                str(c.labor_cost),
                str(c.total_cost),
            ]
        )
        mat_sum += c.material_cost
        lab_sum += c.labor_cost
        grand += c.total_cost
    if len(crows) > 1:
        ct = Table(crows, hAlign="LEFT")
        ct.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ]
            )
        )
        story.append(ct)
        story.append(Spacer(1, 0.1 * inch))
        story.append(
            Paragraph(
                f"<b>Material total:</b> {mat_sum:.2f} &nbsp;&nbsp; "
                f"<b>Labor total:</b> {lab_sum:.2f} &nbsp;&nbsp; "
                f"<b>Grand total:</b> {grand:.2f}",
                styles["Normal"],
            )
        )
    else:
        story.append(Paragraph("No costs calculated yet.", styles["Normal"]))

    doc.build(story)

    report = Report(
        project_id=project.id,
        design_id=design.id if design else None,
        file_path=rel,
    )
    project.status = ProjectStatus.reported
    db.add(report)
    db.commit()
    db.refresh(report)
    return report
