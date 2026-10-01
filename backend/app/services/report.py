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
    AreaEstimate,
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
_ACCENT_SOFT = colors.HexColor("#F0FDFA")


def _indian_group(int_str: str) -> str:
    """Group digits in Indian style: 12,34,567."""
    n = int_str.lstrip("-")
    sign = "-" if int_str.startswith("-") else ""
    if len(n) <= 3:
        return sign + n
    last3 = n[-3:]
    rest = n[:-3]
    parts: list[str] = []
    while rest:
        parts.insert(0, rest[-2:])
        rest = rest[:-2]
    return sign + ",".join(parts + [last3])


def _inr(value: float | None, *, decimals: int = 2) -> str:
    try:
        n = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "—"
    neg = n < 0
    n = abs(n)
    whole = int(n)
    frac = round(n - whole, decimals)
    # Handle float carry
    if frac >= 1:
        whole += 1
        frac = 0.0
    frac_s = f"{frac:.{decimals}f}"[1:] if decimals else ""  # ".xx"
    grouped = _indian_group(str(whole))
    return f"{'−' if neg else ''}₹{grouped}{frac_s}"


def _fmt_qty(value: float | None) -> str:
    try:
        n = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "—"
    if abs(n - round(n)) < 1e-6:
        return _indian_group(str(int(round(n))))
    whole = int(abs(n))
    frac = f"{abs(n) - whole:.2f}"[1:]
    sign = "−" if n < 0 else ""
    return f"{sign}{_indian_group(str(whole))}{frac}"


def _fmt_ft(value: float | None) -> str:
    try:
        n = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "—"
    if abs(n - round(n)) < 1e-6:
        return f"{int(round(n))}"
    return f"{n:.2f}"


def _humanize(text: str | None) -> str:
    if not text:
        return "—"
    return str(text).replace("_", " ").strip().title()


def _styles():
    base = getSampleStyleSheet()
    return {
        "cover_kicker": ParagraphStyle(
            "CoverKicker",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=_TEAL,
            spaceAfter=4,
            leading=10,
            tracking=1,
        ),
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            textColor=_NAVY,
            spaceAfter=2,
            leading=22,
            alignment=TA_LEFT,
        ),
        "cover_sub": ParagraphStyle(
            "CoverSub",
            parent=base["Normal"],
            fontSize=9,
            textColor=_MUTED,
            spaceAfter=6,
            leading=12,
        ),
        "h2": ParagraphStyle(
            "ReportH2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=_NAVY,
            spaceBefore=12,
            spaceAfter=6,
            leading=14,
        ),
        "h3": ParagraphStyle(
            "ReportH3",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=_TEAL,
            spaceBefore=8,
            spaceAfter=4,
            leading=12,
        ),
        "body": ParagraphStyle(
            "ReportBody",
            parent=base["Normal"],
            fontSize=9,
            textColor=_SLATE,
            leading=12,
            spaceAfter=4,
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
            fontSize=8.5,
            textColor=_SLATE,
            leading=11,
        ),
        "cell": ParagraphStyle(
            "ReportCell",
            parent=base["Normal"],
            fontSize=8,
            textColor=_SLATE,
            leading=10,
        ),
        "cell_bold": ParagraphStyle(
            "ReportCellBold",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=_NAVY,
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
        "th": ParagraphStyle(
            "ReportTH",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            textColor=_NAVY,
            leading=9,
        ),
        "th_right": ParagraphStyle(
            "ReportTHRight",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            textColor=_NAVY,
            alignment=TA_RIGHT,
            leading=9,
        ),
        "stat_label": ParagraphStyle(
            "StatLabel",
            parent=base["Normal"],
            fontSize=7.5,
            textColor=_MUTED,
            alignment=TA_CENTER,
            leading=9,
        ),
        "stat_value": ParagraphStyle(
            "StatValue",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=_NAVY,
            alignment=TA_CENTER,
            leading=14,
        ),
        "grand_value": ParagraphStyle(
            "GrandValue",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=_TEAL,
            alignment=TA_CENTER,
            leading=16,
        ),
        "disclaimer": ParagraphStyle(
            "ReportDisclaimer",
            parent=base["Normal"],
            fontSize=7.5,
            textColor=_MUTED,
            leading=10,
            alignment=TA_LEFT,
        ),
        "footer": ParagraphStyle(
            "ReportFooter",
            parent=base["Normal"],
            fontSize=7,
            textColor=_MUTED,
            alignment=TA_CENTER,
        ),
        "caption": ParagraphStyle(
            "ReportCaption",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=_NAVY,
            alignment=TA_CENTER,
            spaceAfter=4,
            leading=10,
        ),
    }


def _th(text: str, right: bool = False) -> Paragraph:
    styles = _styles()
    return Paragraph(escape(text), styles["th_right"] if right else styles["th"])


def _table_style(*, totals: bool = False, money_cols: tuple[int, ...] = ()) -> TableStyle:
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), _HEAD_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), _NAVY),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 1), (-1, -1), _SLATE),
        ("ALIGN", (0, 0), (-1, 0), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, _TEAL),
        ("LINEBELOW", (0, 1), (-1, -2 if totals else -1), 0.3, _LINE),
        ("BOX", (0, 0), (-1, -1), 0.6, _LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ROW_ALT]),
    ]
    for col in money_cols:
        cmds.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))
    if totals:
        cmds.extend(
            [
                ("BACKGROUND", (0, -1), (-1, -1), _TOTAL_BG),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 1.0, _TEAL),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, _ROW_ALT]),
            ]
        )
    return TableStyle(cmds)


def _header_footer(canvas, doc, project_title: str, report_id: str):
    canvas.saveState()
    page_w, page_h = A4
    canvas.setFillColor(_TEAL)
    canvas.rect(0, page_h - 3.5, page_w, 3.5, fill=1, stroke=0)
    canvas.setFillColor(_NAVY)
    canvas.rect(0, page_h - 5.5, page_w, 2, fill=1, stroke=0)

    canvas.setStrokeColor(_LINE)
    canvas.setLineWidth(0.5)
    canvas.line(doc.leftMargin, 14 * mm, page_w - doc.rightMargin, 14 * mm)
    canvas.setFillColor(_MUTED)
    canvas.setFont("Helvetica", 7)
    title = (project_title or "Project")[:42]
    canvas.drawString(doc.leftMargin, 8 * mm, f"{report_id}  ·  {title}")
    canvas.drawRightString(page_w - doc.rightMargin, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _safe_image(path, max_w, max_h):
    try:
        if path is not None and path.exists():
            return RLImage(str(path), width=max_w, height=max_h, kind="proportional")
    except Exception:
        return None
    return None


def _section_rule() -> HRFlowable:
    return HRFlowable(width="100%", thickness=0.8, color=_LINE, spaceBefore=2, spaceAfter=6)


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
    report_ref = f"RR-{project.id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}"
    generated_at = datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")

    doc = SimpleDocTemplate(
        str(dest),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
        title=f"Renovation Report — {project.title}",
        author="FacadePlan",
    )
    story: list = []
    usable_w = A4[0] - doc.leftMargin - doc.rightMargin

    # ── Cover band ──────────────────────────────────────────────
    brand_user = branding_user or db.get(User, project.owner_id)
    logo_flow = None
    if brand_user and brand_user.logo_path:
        logo_flow = _safe_image(absolute_path(brand_user.logo_path), 1.35 * inch, 0.5 * inch)

    company = ""
    contact = ""
    if brand_user:
        company = (brand_user.company or brand_user.full_name or "").strip()
        bits = [x for x in [brand_user.email, brand_user.phone] if x]
        contact = " · ".join(bits)

    left_col = []
    if logo_flow:
        left_col.append(logo_flow)
        left_col.append(Spacer(1, 4))
    left_col.append(Paragraph("FACADE RENOVATION", styles["cover_kicker"]))
    left_col.append(Paragraph("Cost &amp; Quantity Report", styles["cover_title"]))
    left_col.append(
        Paragraph("Advisory planning estimate for contractor discussion", styles["cover_sub"])
    )

    right_lines = [
        f"<b>Ref</b>&nbsp;&nbsp;{escape(report_ref)}",
        f"<b>Date</b>&nbsp;&nbsp;{escape(generated_at)}",
    ]
    if company:
        right_lines.append(f"<b>Prepared by</b>&nbsp;&nbsp;{escape(company)}")
    if contact:
        right_lines.append(f"<font size='7' color='#64748B'>{escape(contact)}</font>")
    right_col = [Paragraph("<br/>".join(right_lines), styles["meta"])]

    cover = Table([[left_col, right_col]], colWidths=[usable_w * 0.58, usable_w * 0.42])
    cover.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("BACKGROUND", (1, 0), (1, 0), _ACCENT_SOFT),
                ("BOX", (1, 0), (1, 0), 0.5, _LINE),
                ("LEFTPADDING", (1, 0), (1, 0), 8),
                ("RIGHTPADDING", (1, 0), (1, 0), 8),
                ("TOPPADDING", (1, 0), (1, 0), 8),
                ("BOTTOMPADDING", (1, 0), (1, 0), 8),
            ]
        )
    )
    story.append(cover)
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=2, color=_TEAL, spaceBefore=0, spaceAfter=4))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_NAVY, spaceBefore=0, spaceAfter=10))

    # ── 1. Project summary ──────────────────────────────────────
    story.append(Paragraph("1. Project summary", styles["h2"]))
    story.append(_section_rule())
    status = project.status.value if hasattr(project.status, "value") else str(project.status)
    design_name = design.name if design else "—"

    # Pull facade size hint from area notes if present
    facade_note = "—"
    area_rows_db = (
        db.query(AreaEstimate)
        .filter(AreaEstimate.project_id == project.id)
        .order_by(AreaEstimate.region_id)
        .all()
    )
    for a in area_rows_db:
        if a.notes and "AI facade" in (a.notes or ""):
            facade_note = a.notes.split(".")[0].replace("AI facade", "").strip()
            break
    method_hint = "—"
    if area_rows_db:
        methods = {a.method for a in area_rows_db if a.method}
        if any("gemini" in (m or "") for m in methods):
            method_hint = "Gemini vision estimate"
        elif methods:
            method_hint = _humanize(next(iter(methods)))

    summary_data = [
        [
            Paragraph("<b>Project</b>", styles["cell_bold"]),
            Paragraph(escape(project.title), styles["cell"]),
            Paragraph("<b>Status</b>", styles["cell_bold"]),
            Paragraph(escape(_humanize(status)), styles["cell"]),
        ],
        [
            Paragraph("<b>Design</b>", styles["cell_bold"]),
            Paragraph(escape(design_name), styles["cell"]),
            Paragraph("<b>Report ID</b>", styles["cell_bold"]),
            Paragraph(escape(report_ref), styles["cell"]),
        ],
        [
            Paragraph("<b>Facade size</b>", styles["cell_bold"]),
            Paragraph(escape(facade_note if facade_note != "—" else "See area schedule"), styles["cell"]),
            Paragraph("<b>Estimate method</b>", styles["cell_bold"]),
            Paragraph(escape(method_hint), styles["cell"]),
        ],
    ]
    if project.description:
        summary_data.append(
            [
                Paragraph("<b>Notes</b>", styles["cell_bold"]),
                Paragraph(escape(project.description), styles["cell"]),
                "",
                "",
            ]
        )
    st_cmds = [
        ("BOX", (0, 0), (-1, -1), 0.6, _LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, _LINE),
        ("BACKGROUND", (0, 0), (0, -1), _HEAD_BG),
        ("BACKGROUND", (2, 0), (2, -1), _HEAD_BG),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    if project.description:
        st_cmds.append(("SPAN", (1, -1), (3, -1)))
        st_cmds.append(("BACKGROUND", (2, -1), (2, -1), colors.white))
    st = Table(
        summary_data,
        colWidths=[1.05 * inch, 2.35 * inch, 1.15 * inch, usable_w - 4.55 * inch],
    )
    st.setStyle(TableStyle(st_cmds))
    story.append(st)

    # ── 2. Before & after ───────────────────────────────────────
    story.append(Paragraph("2. Before &amp; after visuals", styles["h2"]))
    story.append(_section_rule())
    img_w = (usable_w - 10) / 2
    img_h = 2.35 * inch
    orig_img = _safe_image(absolute_path(primary.file_path), img_w - 8, img_h) if primary else None
    redes_img = None
    if design and design.redesign_path:
        redes_img = _safe_image(absolute_path(design.redesign_path), img_w - 8, img_h)

    before_block = [
        Paragraph("BEFORE — Existing exterior", styles["caption"]),
        orig_img or Paragraph("<i>No original photo available</i>", styles["small"]),
    ]
    after_block = [
        Paragraph(f"AFTER — {escape(design_name)}", styles["caption"]),
        redes_img or Paragraph("<i>No redesign generated yet</i>", styles["small"]),
    ]
    vis = Table([[before_block, after_block]], colWidths=[img_w, img_w])
    vis.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (0, 0), 0.6, _LINE),
                ("BOX", (1, 0), (1, 0), 0.6, _LINE),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    story.append(vis)

    # ── 3. Materials ────────────────────────────────────────────
    story.append(Paragraph("3. Selected materials by region", styles["h2"]))
    story.append(_section_rule())
    mat_rows = [
        [
            _th("#"),
            _th("Region"),
            _th("Type"),
            _th("Material"),
            _th("Category"),
            _th("Unit rate", right=True),
        ]
    ]
    if design:
        mappings = (
            db.query(DesignRegionMaterial)
            .filter(DesignRegionMaterial.design_id == design.id)
            .order_by(DesignRegionMaterial.id)
            .all()
        )
        for i, m in enumerate(mappings, start=1):
            region = db.get(StructureRegion, m.region_id)
            mat = db.get(Material, m.material_id)
            rlabel = (region.label if region and region.label else None) or (
                _humanize(region.region_type.value) if region else f"Region {m.region_id}"
            )
            rtype = _humanize(region.region_type.value) if region else "—"
            mname = mat.name if mat else "—"
            mtype = _humanize(mat.material_type.value) if mat else "—"
            rate = f"{_inr(mat.material_rate)} / {mat.unit}" if mat else "—"
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
            colWidths=[
                0.3 * inch,
                1.25 * inch,
                0.95 * inch,
                2.05 * inch,
                1.05 * inch,
                usable_w - 5.6 * inch,
            ],
            repeatRows=1,
        )
        mt.setStyle(_table_style(money_cols=(5,)))
        story.append(KeepTogether([mt]))
    else:
        story.append(Paragraph("No materials assigned for this design yet.", styles["body"]))

    # ── 4. Area schedule ────────────────────────────────────────
    story.append(Paragraph("4. Area schedule", styles["h2"]))
    story.append(_section_rule())
    # Prefer user override when both exist for same region
    best_areas: dict[int, AreaEstimate] = {}
    for a in area_rows_db:
        if a.region_id is None:
            continue
        prev = best_areas.get(a.region_id)
        if prev is None or (a.user_override and not prev.user_override):
            best_areas[a.region_id] = a
    areas_sorted = sorted(best_areas.values(), key=lambda x: (x.region_id or 0))

    a_rows = [
        [
            _th("#"),
            _th("Region"),
            _th("Type"),
            _th("Area (sq ft)", right=True),
            _th("Length (ft)", right=True),
            _th("Method"),
        ]
    ]
    total_area = 0.0
    for i, a in enumerate(areas_sorted, start=1):
        region = db.get(StructureRegion, a.region_id) if a.region_id else None
        label = (region.label if region and region.label else None) or _humanize(
            a.region_type.value if hasattr(a.region_type, "value") else str(a.region_type)
        )
        rtype = _humanize(a.region_type.value if hasattr(a.region_type, "value") else str(a.region_type))
        area_v = float(a.area_sq_ft or 0)
        total_area += area_v
        method = "User override" if a.user_override else (
            "Gemini AI" if a.method and "gemini" in a.method else _humanize(a.method)
        )
        a_rows.append(
            [
                Paragraph(str(i), styles["cell"]),
                Paragraph(escape(label), styles["cell"]),
                Paragraph(escape(rtype), styles["cell"]),
                Paragraph(_fmt_qty(area_v), styles["cell_right"]),
                Paragraph(_fmt_ft(a.length_ft) if a.length_ft is not None else "—", styles["cell_right"]),
                Paragraph(escape(method), styles["cell"]),
            ]
        )
    if len(a_rows) > 1:
        a_rows.append(
            [
                Paragraph("", styles["cell"]),
                Paragraph("<b>Total measured area</b>", styles["cell_bold"]),
                Paragraph("", styles["cell"]),
                Paragraph(f"<b>{_fmt_qty(total_area)}</b>", styles["cell_right"]),
                Paragraph("", styles["cell"]),
                Paragraph("sq ft", styles["cell"]),
            ]
        )
        at = Table(
            a_rows,
            colWidths=[
                0.3 * inch,
                1.5 * inch,
                1.1 * inch,
                1.05 * inch,
                0.95 * inch,
                usable_w - 4.9 * inch,
            ],
            repeatRows=1,
        )
        at.setStyle(_table_style(totals=True, money_cols=(3, 4)))
        story.append(KeepTogether([at]))
    else:
        story.append(
            Paragraph(
                "No area estimates yet. Run <b>Calculate with AI</b> on the Estimate step first.",
                styles["body"],
            )
        )

    # ── 5. Quantities ───────────────────────────────────────────
    story.append(Paragraph("5. Quantity schedule", styles["h2"]))
    story.append(_section_rule())
    q_lines = (
        db.query(QuantityLine)
        .filter(QuantityLine.project_id == project.id)
        .order_by(QuantityLine.category, QuantityLine.id)
        .all()
    )
    q_rows = [
        [
            _th("#"),
            _th("Category"),
            _th("Material"),
            _th("Base", right=True),
            _th("Wastage", right=True),
            _th("Final qty", right=True),
            _th("Unit"),
        ]
    ]
    for i, q in enumerate(q_lines, start=1):
        mat = db.get(Material, q.material_id) if q.material_id else None
        q_rows.append(
            [
                Paragraph(str(i), styles["cell"]),
                Paragraph(escape(_humanize(q.category)), styles["cell"]),
                Paragraph(escape(mat.name if mat else "—"), styles["cell"]),
                Paragraph(_fmt_qty(q.base_quantity), styles["cell_right"]),
                Paragraph(f"{_fmt_qty(q.wastage_percent)}%", styles["cell_right"]),
                Paragraph(_fmt_qty(q.final_quantity), styles["cell_right"]),
                Paragraph(escape(q.unit or "—"), styles["cell"]),
            ]
        )
    if len(q_rows) > 1:
        qt = Table(
            q_rows,
            colWidths=[
                0.3 * inch,
                1.05 * inch,
                2.15 * inch,
                0.8 * inch,
                0.75 * inch,
                0.9 * inch,
                usable_w - 5.95 * inch,
            ],
            repeatRows=1,
        )
        qt.setStyle(_table_style(money_cols=(3, 4, 5)))
        story.append(KeepTogether([qt]))
    else:
        story.append(
            Paragraph("No quantities calculated yet. Complete the estimate step first.", styles["body"])
        )

    # ── 6. Costs ────────────────────────────────────────────────
    story.append(Paragraph("6. Cost breakdown (INR)", styles["h2"]))
    story.append(_section_rule())
    c_lines = (
        db.query(CostLine)
        .filter(CostLine.project_id == project.id)
        .order_by(CostLine.category, CostLine.id)
        .all()
    )
    c_rows = [
        [
            _th("#"),
            _th("Material / category"),
            _th("Qty", right=True),
            _th("Mat. rate", right=True),
            _th("Labor rate", right=True),
            _th("Material", right=True),
            _th("Labor", right=True),
            _th("Line total", right=True),
        ]
    ]
    mat_sum = lab_sum = grand = 0.0
    for i, c in enumerate(c_lines, start=1):
        mat = db.get(Material, c.material_id) if c.material_id else None
        label = mat.name if mat else _humanize(c.category)
        sub = _humanize(c.category) if mat else ""
        name_cell = escape(label)
        if sub and mat:
            name_cell = f"{escape(label)}<br/><font size='6.5' color='#64748B'>{escape(sub)}</font>"
        mat_sum += float(c.material_cost or 0)
        lab_sum += float(c.labor_cost or 0)
        grand += float(c.total_cost or 0)
        c_rows.append(
            [
                Paragraph(str(i), styles["cell"]),
                Paragraph(name_cell, styles["cell"]),
                Paragraph(f"{_fmt_qty(c.quantity)} {escape(c.unit or '')}".strip(), styles["cell_right"]),
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
                Paragraph("", styles["cell"]),
                Paragraph("<b>TOTALS</b>", styles["cell_bold"]),
                Paragraph("", styles["cell"]),
                Paragraph("", styles["cell"]),
                Paragraph("", styles["cell"]),
                Paragraph(f"<b>{_inr(mat_sum)}</b>", styles["cell_right"]),
                Paragraph(f"<b>{_inr(lab_sum)}</b>", styles["cell_right"]),
                Paragraph(f"<b>{_inr(grand)}</b>", styles["cell_right"]),
            ]
        )
        ct = Table(
            c_rows,
            colWidths=[
                0.28 * inch,
                1.55 * inch,
                0.75 * inch,
                0.85 * inch,
                0.85 * inch,
                0.95 * inch,
                0.85 * inch,
                usable_w - 6.08 * inch,
            ],
            repeatRows=1,
        )
        ct.setStyle(_table_style(totals=True, money_cols=(2, 3, 4, 5, 6, 7)))
        story.append(KeepTogether([ct]))
        story.append(Spacer(1, 10))

        # Grand total highlight cards
        summary_box = Table(
            [
                [
                    [
                        Paragraph("MATERIAL TOTAL", styles["stat_label"]),
                        Paragraph(_inr(mat_sum), styles["stat_value"]),
                    ],
                    [
                        Paragraph("LABOR TOTAL", styles["stat_label"]),
                        Paragraph(_inr(lab_sum), styles["stat_value"]),
                    ],
                    [
                        Paragraph("GRAND TOTAL (INR)", styles["stat_label"]),
                        Paragraph(_inr(grand), styles["grand_value"]),
                    ],
                ]
            ],
            colWidths=[usable_w / 3.0] * 3,
        )
        summary_box.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (1, 0), _HEAD_BG),
                    ("BACKGROUND", (2, 0), (2, 0), _TOTAL_BG),
                    ("BOX", (0, 0), (-1, -1), 1.2, _TEAL),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, _LINE),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ]
            )
        )
        story.append(summary_box)
    else:
        story.append(
            Paragraph("No cost lines yet. Complete the estimate step first.", styles["body"])
        )

    # ── 7. Disclaimer ───────────────────────────────────────────
    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=1.2, color=_TEAL, spaceBefore=4, spaceAfter=8))
    story.append(Paragraph("7. Notes &amp; disclaimer", styles["h2"]))
    story.append(
        Paragraph(
            "This document is an <b>advisory planning estimate</b> generated from the project photo, "
            "detected facade regions, selected materials, and configured unit rates. "
            "Facade size and quantities may be AI-assisted (Gemini) and should be verified on site. "
            "Figures include stated wastage allowances and are <b>not a quotation, contract, or "
            "legally binding offer</b>. Confirm measurements, structure, local codes, and supplier "
            "rates with a licensed contractor or consultant before procurement or construction.",
            styles["disclaimer"],
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "FacadePlan · Currency: Indian Rupee (INR) · All amounts formatted in Indian numbering",
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
