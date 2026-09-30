import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RoleName(str, enum.Enum):
    homeowner = "homeowner"
    contractor = "contractor"
    architect = "architect"
    builder = "builder"
    consultant = "consultant"
    supplier = "supplier"
    admin = "admin"


class ProjectStatus(str, enum.Enum):
    draft = "draft"
    designed = "designed"
    estimated = "estimated"
    reported = "reported"


class RegionType(str, enum.Enum):
    main_wall = "main_wall"
    window = "window"
    balcony = "balcony"
    pillar = "pillar"
    parapet = "parapet"
    gate = "gate"
    roof_edge = "roof_edge"
    railing = "railing"
    other = "other"


class MaterialType(str, enum.Enum):
    paint = "paint"
    stone_cladding = "stone_cladding"
    tiles = "tiles"
    texture_finish = "texture_finish"
    glass_railing = "glass_railing"
    metal_railing = "metal_railing"
    panels = "panels"
    other = "other"


class MemberRole(str, enum.Enum):
    owner = "owner"
    editor = "editor"
    viewer = "viewer"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50))
    company: Mapped[str | None] = mapped_column(String(255))
    logo_path: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    roles: Mapped[list["UserRole"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    projects: Mapped[list["Project"]] = relationship(back_populates="owner")


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[RoleName] = mapped_column(Enum(RoleName, name="role_name", native_enum=True), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))

    users: Mapped[list["UserRole"]] = relationship(back_populates="role")


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)

    user: Mapped[User] = relationship(back_populates="roles")
    role: Mapped[Role] = relationship(back_populates="users")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status", native_enum=False), default=ProjectStatus.draft
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped[User] = relationship(back_populates="projects")
    members: Mapped[list["ProjectMember"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    images: Mapped[list["ProjectImage"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    regions: Mapped[list["StructureRegion"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    designs: Mapped[list["Design"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    area_estimates: Mapped[list["AreaEstimate"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    quantity_lines: Mapped[list["QuantityLine"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    cost_lines: Mapped[list["CostLine"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    rate_overrides: Mapped[list["RateOverride"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    reports: Mapped[list["Report"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    member_role: Mapped[MemberRole] = mapped_column(
        Enum(MemberRole, name="member_role", native_enum=False), default=MemberRole.viewer
    )

    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class ProjectImage(Base):
    __tablename__ = "project_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    quality_ok: Mapped[bool | None] = mapped_column(Boolean)
    quality_message: Mapped[str | None] = mapped_column(Text)
    width_px: Mapped[int | None] = mapped_column(Integer)
    height_px: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="images")


class StructureRegion(Base):
    __tablename__ = "structure_regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    region_type: Mapped[RegionType] = mapped_column(Enum(RegionType, name="region_type", native_enum=False), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255))
    # Normalized polygon points [{x,y}, ...] in 0..1 image space
    points: Mapped[dict | list] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    user_corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="regions")


class Material(Base):
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    material_type: Mapped[MaterialType] = mapped_column(
        Enum(MaterialType, name="material_type", native_enum=False), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(50), default="sq_ft")
    coverage_per_unit: Mapped[float] = mapped_column(Float, default=1.0)
    wastage_percent: Mapped[float] = mapped_column(Float, default=10.0)
    material_rate: Mapped[float] = mapped_column(Float, default=0.0)
    labor_rate: Mapped[float] = mapped_column(Float, default=0.0)
    durability_notes: Mapped[str | None] = mapped_column(Text)
    maintenance_notes: Mapped[str | None] = mapped_column(Text)
    suitable_regions: Mapped[list | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    textures: Mapped[list["MaterialTexture"]] = relationship(
        back_populates="material", cascade="all, delete-orphan"
    )


class MaterialTexture(Base):
    __tablename__ = "material_textures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id", ondelete="CASCADE"), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255))

    material: Mapped[Material] = relationship(back_populates="textures")


class Design(Base):
    __tablename__ = "designs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    redesign_path: Mapped[str | None] = mapped_column(String(500))
    prompt_used: Mapped[str | None] = mapped_column(Text)
    hq_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="designs")
    region_materials: Mapped[list["DesignRegionMaterial"]] = relationship(
        back_populates="design", cascade="all, delete-orphan"
    )


class DesignRegionMaterial(Base):
    __tablename__ = "design_region_materials"
    __table_args__ = (UniqueConstraint("design_id", "region_id", name="uq_design_region"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    design_id: Mapped[int] = mapped_column(ForeignKey("designs.id", ondelete="CASCADE"), nullable=False)
    region_id: Mapped[int] = mapped_column(ForeignKey("structure_regions.id", ondelete="CASCADE"), nullable=False)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), nullable=False)

    design: Mapped[Design] = relationship(back_populates="region_materials")
    region: Mapped[StructureRegion] = relationship()
    material: Mapped[Material] = relationship()


class AreaEstimate(Base):
    __tablename__ = "area_estimates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("structure_regions.id", ondelete="SET NULL"))
    region_type: Mapped[RegionType] = mapped_column(Enum(RegionType, name="region_type", native_enum=False))
    area_sq_ft: Mapped[float] = mapped_column(Float, default=0.0)
    length_ft: Mapped[float | None] = mapped_column(Float)
    method: Mapped[str | None] = mapped_column(String(100))
    confidence: Mapped[float | None] = mapped_column(Float)
    user_override: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="area_estimates")


class QuantityLine(Base):
    __tablename__ = "quantity_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(100))
    base_quantity: Mapped[float] = mapped_column(Float, default=0.0)
    wastage_percent: Mapped[float] = mapped_column(Float, default=10.0)
    final_quantity: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str] = mapped_column(String(50), default="sq_ft")
    user_override: Mapped[bool] = mapped_column(Boolean, default=False)

    project: Mapped[Project] = relationship(back_populates="quantity_lines")
    material: Mapped[Material] = relationship()


class CostLine(Base):
    __tablename__ = "cost_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    material_id: Mapped[int | None] = mapped_column(ForeignKey("materials.id"))
    category: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str] = mapped_column(String(50), default="sq_ft")
    material_rate: Mapped[float] = mapped_column(Float, default=0.0)
    labor_rate: Mapped[float] = mapped_column(Float, default=0.0)
    material_cost: Mapped[float] = mapped_column(Float, default=0.0)
    labor_cost: Mapped[float] = mapped_column(Float, default=0.0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)

    project: Mapped[Project] = relationship(back_populates="cost_lines")
    material: Mapped[Material | None] = relationship()


class RateOverride(Base):
    __tablename__ = "rate_overrides"
    __table_args__ = (UniqueConstraint("project_id", "material_id", name="uq_project_material_rate"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), nullable=False)
    material_rate: Mapped[float | None] = mapped_column(Float)
    labor_rate: Mapped[float | None] = mapped_column(Float)

    project: Mapped[Project] = relationship(back_populates="rate_overrides")
    material: Mapped[Material] = relationship()


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    design_id: Mapped[int | None] = mapped_column(ForeignKey("designs.id", ondelete="SET NULL"))
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="reports")

