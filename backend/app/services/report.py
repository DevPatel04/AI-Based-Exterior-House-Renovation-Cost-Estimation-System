"""Professional exterior renovation PDF report (ReportLab)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch, mm
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.orm import Session

from app.models import (
    CostLine,
    Design,
    DesignRegionMaterial,
    Material,
    Project,
    ProjectImage,
    ProjectStatus,
    QuantityLine,
    Report,
    StructureRegion,
    User,
)
from app.services.storage import absolute_path, ensure_upload_dirs

# Brand palette (print-safe)
_NAVY = colors.HexColor("#0F2744")
_TEAL = colors.HexColor("#0D7377")
_SLATE = colors.HexColor("#334155")
_MUTED = colors.HexColor("#64748B")
_LINE = colors.HexColor("#CBD5E1")
_HEAD_BG = colors.HexColor("#E8EEF4")
_ROW_ALT = colors.HexColor("#F8FAFC")
_TOTAL_BG = colors.HexColor("#ECFDF5")


def _inr(value: float) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    # Indian-style grouping approximately via format then leave as ₹
    return f"₹{n:,.2f}"


def _fmt_qty(value: float) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    if abs(n - round(n)) < 1e-6:
        return f"{int(round(n))}"
    return f"{n:,.2f}"


def _styles():
    base = getSampleStyleSheet()
    styles = {
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            textColor=_NAVY,
            spaceAfter=4,
            leading=24,
        ),
        "cover_sub": ParagraphStyle(
            "CoverSub",
            parent=base["Normal"],
            fontSize=10,
            textColor=_MUTED,
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "ReportH2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=_NAVY,
            spaceBefore=14,
            spaceAfter=8,
            borderPadding=0,
        ),
        "body": ParagraphStyle(
            "ReportBody",
            parent=base["Normal"],
            fontSize=9,
            textColor=_SLATE,
            leading=12,
        ),
        "small": ParagraphStyle(
            "ReportSmall",
            parent=base["Normal"],
            fontSize=8,
            textColor=_MUTED,
            leading=10,
        ),
        "meta": ParagraphStyle(
            "ReportMeta",
            parent=base["Normal"],
            fontSize=9,
            textColor=_SLATE,
            leading=12,
        ),
        "cell": ParagraphStyle(
            "ReportCell",
            parent=base["Normal"],
            fontSize=8,
            textColor=_SLATE,
            leading=10,
        ),
        "cell_right": ParagraphStyle(
            "ReportCellRight",
            parent=base["Normal"],
            fontSize=8,
            textColor=_SLATE,
            alignment=TA_RIGHT,
            leading=10,
        ),
        "disclaimer": ParagraphStyle(
            "ReportDisclaimer",
            parent=base["Normal"],
            fontSize=8,
            textColor=_MUTED,
            leading=11,
            alignment=TA_LEFT,
        ),
        "footer": ParagraphStyle(
            "ReportFooter",
            parent=base["Normal"],
            fontSize=7,
            textColor=_MUTED,
            alignment=TA_CENTER,
        ),
    }
    return styles


def _table_style(has_totals_row: bool = False) -> TableStyle:
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), _HEAD_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), _NAVY),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 1), (-1, -1), _SLATE),
        ("ALIGN", (0, 0), (-1, 0), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, _LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ROW_ALT]),
    ]
    if has_totals_row:
        cmds.extend(
            [
                ("BACKGROUND", (0, -1), (-1, -1), _TOTAL_BG),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, _ROW_ALT]),
            ]
        )
    return TableStyle(cmds)


def _header_footer(canvas, doc, project_title: str, report_id: str):
    canvas.saveState()
    page_w, page_h = A4
    # Top accent
    canvas.setFillColor(_TEAL)
    canvas.rect(0, page_h - 4, page_w, 4, fill=1, stroke=0)
    # Footer line
    canvas.setStrokeColor(_LINE)
    canvas.setLineWidth(0.5)
    canvas.line(doc.leftMargin, 16 * mm, page_w - doc.rightMargin, 16 * mm)
    canvas.setFillColor(_MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(doc.leftMargin, 10 * mm, f"Ref: {report_id}  ·  {escape(project_title)[:48]}")
    canvas.drawRightString(page_w - doc.rightMargin, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _safe_image(path, max_w, max_h):
    try:
        if path.exists():
            return RLImage(str(path), width=max_w, height=max_h, kind="proportional")
    except Exception:
        return None
    return None


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
    styles = _styles()
    report_ref = f"RR-{project.id}-{datetime.now(timezone.utc).strftime('%Y%m%d')}"
    generated_at = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")

    doc = SimpleDocTemplate(
        str(dest),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=22 * mm,
        title=f"Renovation Report — {project.title}",
        author="House Renovation Planner",
    )
    story: list = []
    usable_w = A4[0] - doc.leftMargin - doc.rightMargin

    # —— Cover / identity ——
    brand_user = branding_user or db.get(User, project.owner_id)
    brand_bits: list = []
    if brand_user and brand_user.logo_path:
        logo = _safe_image(absolute_path(brand_user.logo_path), 1.4 * inch, 0.55 * inch)
        if logo:
            brand_bits.append(logo)
    company = ""
    if brand_user:
        company = brand_user.company or brand_user.full_name or ""
    right_meta = [
        Paragraph("<b>Exterior Renovation Cost Report</b>", styles["cover_title"]),
        Paragraph("Planning estimate for contractor discussion", styles["cover_sub"]),
        Paragraph(f"Document ref: <b>{escape(report_ref)}</b>", styles["meta"]),
        Paragraph(f"Generated: {escape(generated_at)}", styles["meta"]),
    ]
    if company:
        right_meta.insert(2, Paragraph(f"Prepared by: <b>{escape(company)}</b>", styles["meta"]))

    header_row = [brand_bits[0] if brand_bits else "", right_meta]
    ht = Table([header_row], colWidths=[1.6 * inch, usable_w - 1.6 * inch])
    ht.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(ht)
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1.5, color=_TEAL, spaceBefore=2, spaceAfter=10))

    # —— Project summary ——
    story.append(Paragraph("1. Project summary", styles["h2"]))
    status = project.status.value if hasattr(project.status, "value") else str(project.status)
    design_name = design.name if design else "—"
    summary_data = [
        [
            Paragraph("<b>Project</b>", styles["cell"]),
            Paragraph(escape(project.title), styles["cell"]),
            Paragraph("<b>Status</b>", styles["cell"]),
            Paragraph(escape(status.replace("_", " ").title()), styles["cell"]),
        ],
        [
            Paragraph("<b>Design</b>", styles["cell"]),
            Paragraph(escape(design_name), styles["cell"]),
            Paragraph("<b>Report ID</b>", styles["cell"]),
            Paragraph(escape(report_ref), styles["cell"]),
        ],
    ]
    if project.description:
        summary_data.append(
            [
                Paragraph("<b>Notes</b>", styles["cell"]),
                Paragraph(escape(project.description), styles["cell"]),
                "",
                "",
            ]
        )
    st_cmds = [
        ("BOX", (0, 0), (-1, -1), 0.6, _LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, _LINE),
        ("BACKGROUND", (0, 0), (0, -1), _HEAD_BG),
        ("BACKGROUND", (2, 0), (2, -1), _HEAD_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if project.description:
        st_cmds.append(("SPAN", (1, 2), (3, 2)))
        st_cmds.append(("BACKGROUND", (2, 2), (2, 2), colors.white))
    st = Table(summary_data, colWidths=[0.9 * inch, 2.4 * inch, 0.9 * inch, usable_w - 4.2 * inch])
    st.setStyle(TableStyle(st_cmds))
    story.append(st)

    # —— Visuals ——
    story.append(Paragraph("2. Before & after", styles["h2"]))
    orig_img = _safe_image(absolute_path(primary.file_path), 3.2 * inch, 2.3 * inch) if primary else None
    redes_img = None
    if design and design.redesign_path:
        redes_img = _safe_image(absolute_path(design.redesign_path), 3.2 * inch, 2.3 * inch)

    before_block = [
        Paragraph("<b>Before — existing exterior</b>", styles["small"]),
        Spacer(1, 4),
        orig_img or Paragraph("<i>No original photo available</i>", styles["small"]),
    ]
    after_block = [
        Paragraph(f"<b>After — {escape(design_name)}</b>", styles["small"]),
        Spacer(1, 4),
        redes_img or Paragraph("<i>No redesign generated yet</i>", styles["small"]),
    ]
    vis = Table([[before_block, after_block]], colWidths=[usable_w / 2 - 4, usable_w / 2 - 4])
    vis.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (0, 0), 0.5, _LINE),
                ("BOX", (1, 0), (1, 0), 0.5, _LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ]
        )
    )
    story.append(vis)

    # —— Materials ——
    story.append(Paragraph("3. Selected materials by region", styles["h2"]))
    mat_rows = [
        [
            Paragraph("<b>#</b>", styles["cell"]),
            Paragraph("<b>Region</b>", styles["cell"]),
            Paragraph("<b>Type</b>", styles["cell"]),
            Paragraph("<b>Material</b>", styles["cell"]),
            Paragraph("<b>Category</b>", styles["cell"]),
            Paragraph("<b>Rate</b>", styles["cell_right"]),
        ]
    ]
    if design:
        mappings = (
            db.query(DesignRegionMaterial)
            .filter(DesignRegionMaterial.design_id == design.id)
            .all()
        )
        for i, m in enumerate(mappings, start=1):
            region = db.get(StructureRegion, m.region_id)
            mat = db.get(Material, m.material_id)
            rlabel = (region.label if region and region.label else None) or (
                region.region_type.value.replace("_", " ").title() if region else f"Region {m.region_id}"
            )
            rtype = region.region_type.value.replace("_", " ") if region else "—"
            mname = mat.name if mat else "—"
            mtype = mat.material_type.value.replace("_", " ") if mat else "—"
            rate = _inr(mat.material_rate) + (f"/{mat.unit}" if mat else "") if mat else "—"
            mat_rows.append(
                [
                    Paragraph(str(i), styles["cell"]),
                    Paragraph(escape(rlabel), styles["cell"]),
                    Paragraph(escape(rtype), styles["cell"]),
                    Paragraph(escape(mname), styles["cell"]),
                    Paragraph(escape(mtype), styles["cell"]),
                    Paragraph(escape(rate), styles["cell_right"]),
                ]
            )
    if len(mat_rows) > 1:
        mt = Table(
            mat_rows,
            colWidths=[0.35 * inch, 1.3 * inch, 0.95 * inch, 2.0 * inch, 1.0 * inch, usable_w - 5.6 * inch],
        )
        mt.setStyle(_table_style())
        story.append(mt)
    else:
        story.append(Paragraph("No materials assigned for this design.", styles["body"]))

    # —— Quantities ——
    story.append(Paragraph("4. Quantity schedule", styles["h2"]))
    q_lines = db.query(QuantityLine).filter(QuantityLine.project_id == project.id).all()
    q_rows = [
        [
            Paragraph("<b>Category</b>", styles["cell"]),
            Paragraph("<b>Material</b>", styles["cell"]),
            Paragraph("<b>Base</b>", styles["cell_right"]),
            Paragraph("<b>Wastage</b>", styles["cell_right"]),
            Paragraph("<b>Final qty</b>", styles["cell_right"]),
            Paragraph("<b>Unit</b>", styles["cell"]),
        ]
    ]
    for q in q_lines:
        mat = db.get(Material, q.material_id) if q.material_id else None
        q_rows.append(
            [
                Paragraph(escape((q.category or "—").replace("_", " ")), styles["cell"]),
                Paragraph(escape(mat.name if mat else (str(q.material_id) if q.material_id else "—")), styles["cell"]),
                Paragraph(_fmt_qty(q.base_quantity), styles["cell_right"]),
                Paragraph(f"{_fmt_qty(q.wastage_percent)}%", styles["cell_right"]),
                Paragraph(_fmt_qty(q.final_quantity), styles["cell_right"]),
                Paragraph(escape(q.unit or "—"), styles["cell"]),
            ]
        )
    if len(q_rows) > 1:
        qt = Table(
            q_rows,
            colWidths=[1.1 * inch, 2.2 * inch, 0.85 * inch, 0.85 * inch, 0.95 * inch, usable_w - 5.95 * inch],
        )
        qt.setStyle(_table_style())
        story.append(qt)
    else:
        story.append(Paragraph("No quantities calculated yet. Run estimate before reporting.", styles["body"]))

    # —— Costs ——
    story.append(Paragraph("5. Cost breakdown", styles["h2"]))
    c_lines = db.query(CostLine).filter(CostLine.project_id == project.id).all()
    c_rows = [
        [
            Paragraph("<b>Category</b>", styles["cell"]),
            Paragraph("<b>Qty</b>", styles["cell_right"]),
            Paragraph("<b>Mat. rate</b>", styles["cell_right"]),
            Paragraph("<b>Labor rate</b>", styles["cell_right"]),
            Paragraph("<b>Material</b>", styles["cell_right"]),
            Paragraph("<b>Labor</b>", styles["cell_right"]),
            Paragraph("<b>Line total</b>", styles["cell_right"]),
        ]
    ]
    mat_sum = lab_sum = grand = 0.0
    for c in c_lines:
        mat_sum += float(c.material_cost or 0)
        lab_sum += float(c.labor_cost or 0)
        grand += float(c.total_cost or 0)
        c_rows.append(
            [
                Paragraph(escape((c.category or "—").replace("_", " ")), styles["cell"]),
                Paragraph(_fmt_qty(c.quantity), styles["cell_right"]),
                Paragraph(_inr(c.material_rate), styles["cell_right"]),
                Paragraph(_inr(c.labor_rate), styles["cell_right"]),
                Paragraph(_inr(c.material_cost), styles["cell_right"]),
                Paragraph(_inr(c.labor_cost), styles["cell_right"]),
                Paragraph(_inr(c.total_cost), styles["cell_right"]),
            ]
        )
    if len(c_rows) > 1:
        c_rows.append(
            [
                Paragraph("<b>Totals</b>", styles["cell"]),
                "",
                "",
                "",
                Paragraph(f"<b>{_inr(mat_sum)}</b>", styles["cell_right"]),
                Paragraph(f"<b>{_inr(lab_sum)}</b>", styles["cell_right"]),
                Paragraph(f"<b>{_inr(grand)}</b>", styles["cell_right"]),
            ]
        )
        ct = Table(
            c_rows,
            colWidths=[
                1.15 * inch,
                0.7 * inch,
                0.95 * inch,
                0.95 * inch,
                1.0 * inch,
                0.95 * inch,
                usable_w - 5.7 * inch,
            ],
        )
        ct.setStyle(_table_style(has_totals_row=True))
        story.append(ct)
        story.append(Spacer(1, 8))
        summary_box = Table(
            [
                [
                    Paragraph("<b>Material total</b><br/>" + _inr(mat_sum), styles["cell"]),
                    Paragraph("<b>Labor total</b><br/>" + _inr(lab_sum), styles["cell"]),
                    Paragraph("<b>Grand total (INR)</b><br/>" + f"<font size='11'><b>{_inr(grand)}</b></font>", styles["cell"]),
                ]
            ],
            colWidths=[usable_w / 3.0] * 3,
        )
        summary_box.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), _TOTAL_BG),
                    ("BOX", (0, 0), (-1, -1), 1, _TEAL),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, _LINE),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.append(summary_box)
    else:
        story.append(Paragraph("No cost lines yet. Complete the estimate step first.", styles["body"]))

    # —— Disclaimer ——
    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.6, color=_LINE, spaceBefore=4, spaceAfter=8))
    story.append(Paragraph("6. Notes & disclaimer", styles["h2"]))
    story.append(
        Paragraph(
            "This document is an <b>advisory planning estimate</b> generated from user-selected materials, "
            "detected facade regions, and configured unit rates. Quantities include stated wastage allowances. "
            "Figures are indicative only and are <b>not a quotation, contract, or legally binding offer</b>. "
            "Verify site measurements, structural constraints, local codes, and supplier rates with a licensed "
            "contractor or consultant before procurement or construction.",
            styles["disclaimer"],
        )
    )
    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "Prepared with House Renovation Planner · Currency: Indian Rupee (INR)",
            styles["footer"],
        )
    )

    def _on_page(canvas, doc_):
        _header_footer(canvas, doc_, project.title, report_ref)

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)

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
