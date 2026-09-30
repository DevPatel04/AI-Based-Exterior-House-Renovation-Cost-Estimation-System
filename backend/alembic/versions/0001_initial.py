"""Initial schema for house renovation platform

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    role_name = sa.Enum(
        "homeowner",
        "contractor",
        "architect",
        "builder",
        "consultant",
        "supplier",
        "admin",
        name="role_name",
    )
    project_status = sa.Enum("draft", "designed", "estimated", "reported", name="project_status")
    region_type = sa.Enum(
        "main_wall",
        "window",
        "balcony",
        "pillar",
        "parapet",
        "gate",
        "roof_edge",
        "railing",
        "other",
        name="region_type",
    )
    material_type = sa.Enum(
        "paint",
        "stone_cladding",
        "tiles",
        "texture_finish",
        "glass_railing",
        "metal_railing",
        "panels",
        "other",
        name="material_type",
    )
    member_role = sa.Enum("owner", "editor", "viewer", name="member_role")

    role_name.create(op.get_bind(), checkfirst=True)
    project_status.create(op.get_bind(), checkfirst=True)
    region_type.create(op.get_bind(), checkfirst=True)
    material_type.create(op.get_bind(), checkfirst=True)
    member_role.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(50)),
        sa.Column("company", sa.String(255)),
        sa.Column("logo_path", sa.String(500)),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", role_name, nullable=False, unique=True),
        sa.Column("description", sa.String(255)),
    )

    op.create_table(
        "user_roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_role"),
    )

    op.create_table(
        "materials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("material_type", material_type, nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("unit", sa.String(50), server_default="sq_ft"),
        sa.Column("coverage_per_unit", sa.Float(), server_default="1"),
        sa.Column("wastage_percent", sa.Float(), server_default="10"),
        sa.Column("material_rate", sa.Float(), server_default="0"),
        sa.Column("labor_rate", sa.Float(), server_default="0"),
        sa.Column("durability_notes", sa.Text()),
        sa.Column("maintenance_notes", sa.Text()),
        sa.Column("suitable_regions", postgresql.JSONB()),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("approved", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "material_textures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("materials.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("label", sa.String(255)),
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", project_status, server_default="draft"),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("is_archived", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "project_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_role", member_role, server_default="viewer"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_member"),
    )

    op.create_table(
        "project_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("original_filename", sa.String(255)),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("quality_ok", sa.Boolean()),
        sa.Column("quality_message", sa.Text()),
        sa.Column("width_px", sa.Integer()),
        sa.Column("height_px", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "structure_regions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("region_type", region_type, nullable=False),
        sa.Column("label", sa.String(255)),
        sa.Column("points", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("user_corrected", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "designs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("redesign_path", sa.String(500)),
        sa.Column("prompt_used", sa.Text()),
        sa.Column("hq_mode", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "design_region_materials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("design_id", sa.Integer(), sa.ForeignKey("designs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("region_id", sa.Integer(), sa.ForeignKey("structure_regions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("materials.id"), nullable=False),
        sa.UniqueConstraint("design_id", "region_id", name="uq_design_region"),
    )

    op.create_table(
        "area_estimates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("region_id", sa.Integer(), sa.ForeignKey("structure_regions.id", ondelete="SET NULL")),
        sa.Column("region_type", region_type, nullable=False),
        sa.Column("area_sq_ft", sa.Float(), server_default="0"),
        sa.Column("length_ft", sa.Float()),
        sa.Column("method", sa.String(100)),
        sa.Column("confidence", sa.Float()),
        sa.Column("user_override", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("notes", sa.Text()),
    )

    op.create_table(
        "quantity_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("materials.id"), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("base_quantity", sa.Float(), server_default="0"),
        sa.Column("wastage_percent", sa.Float(), server_default="10"),
        sa.Column("final_quantity", sa.Float(), server_default="0"),
        sa.Column("unit", sa.String(50), server_default="sq_ft"),
        sa.Column("user_override", sa.Boolean(), server_default=sa.text("false")),
    )

    op.create_table(
        "cost_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("materials.id")),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Float(), server_default="0"),
        sa.Column("unit", sa.String(50), server_default="sq_ft"),
        sa.Column("material_rate", sa.Float(), server_default="0"),
        sa.Column("labor_rate", sa.Float(), server_default="0"),
        sa.Column("material_cost", sa.Float(), server_default="0"),
        sa.Column("labor_cost", sa.Float(), server_default="0"),
        sa.Column("total_cost", sa.Float(), server_default="0"),
    )

    op.create_table(
        "rate_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("materials.id"), nullable=False),
        sa.Column("material_rate", sa.Float()),
        sa.Column("labor_rate", sa.Float()),
        sa.UniqueConstraint("project_id", "material_id", name="uq_project_material_rate"),
    )

    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("design_id", sa.Integer(), sa.ForeignKey("designs.id", ondelete="SET NULL")),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )


def downgrade() -> None:
    for table in [
        "reports",
        "rate_overrides",
        "cost_lines",
        "quantity_lines",
        "area_estimates",
        "design_region_materials",
        "designs",
        "structure_regions",
        "project_images",
        "project_members",
        "projects",
        "material_textures",
        "materials",
        "user_roles",
        "roles",
        "users",
    ]:
        op.drop_table(table)
    for enum_name in ["member_role", "material_type", "region_type", "project_status", "role_name"]:
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
