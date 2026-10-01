from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models import (
    MaterialType,
    MemberRole,
    ProjectStatus,
    RegionType,
    RoleName,
)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    company: str | None = Field(default=None, max_length=255)
    role: RoleName = RoleName.homeowner


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    company: str | None = Field(default=None, max_length=255)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=8, max_length=72)


class RoleOut(BaseModel):
    id: int
    name: RoleName
    description: str | None

    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    id: int
    email: str  # str (not EmailStr) so seeded / legacy addresses still serialize
    full_name: str
    phone: str | None
    company: str | None
    logo_path: str | None
    is_active: bool
    roles: list[RoleOut] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class AssignRoleIn(BaseModel):
    role: RoleName


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    status: ProjectStatus | None = None
    is_archived: bool | None = None


class ProjectMemberIn(BaseModel):
    user_email: EmailStr
    member_role: MemberRole = MemberRole.viewer


class ProjectMemberOut(BaseModel):
    id: int
    user_id: int
    member_role: MemberRole
    email: str | None = None
    full_name: str | None = None

    model_config = {"from_attributes": True}


class ProjectOut(BaseModel):
    id: int
    title: str
    description: str | None
    status: ProjectStatus
    owner_id: int
    is_archived: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ImageOut(BaseModel):
    id: int
    project_id: int
    file_path: str
    original_filename: str | None
    is_primary: bool
    quality_ok: bool | None
    quality_message: str | None
    width_px: int | None
    height_px: int | None

    model_config = {"from_attributes": True}


class Point(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class RegionCreate(BaseModel):
    region_type: RegionType
    label: str | None = Field(default=None, max_length=255)
    points: list[Point] = Field(min_length=3)
    confidence: float | None = Field(default=None, ge=0, le=1)
    user_corrected: bool = False


class RegionUpdate(BaseModel):
    region_type: RegionType | None = None
    label: str | None = Field(default=None, max_length=255)
    points: list[Point] | None = Field(default=None, min_length=3)
    user_corrected: bool | None = True


class RegionOut(BaseModel):
    id: int
    project_id: int
    region_type: RegionType
    label: str | None
    points: list
    confidence: float | None
    user_corrected: bool

    model_config = {"from_attributes": True}


class MaterialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    material_type: MaterialType
    description: str | None = None
    unit: str = Field(default="sq_ft", max_length=50)
    coverage_per_unit: float = Field(default=1.0, gt=0)
    wastage_percent: float = Field(default=10.0, ge=0, le=100)
    material_rate: float = Field(ge=0)
    labor_rate: float = Field(ge=0)
    durability_notes: str | None = None
    maintenance_notes: str | None = None
    suitable_regions: list[str] | None = None


class MaterialUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    unit: str | None = Field(default=None, max_length=50)
    coverage_per_unit: float | None = Field(default=None, gt=0)
    wastage_percent: float | None = Field(default=None, ge=0, le=100)
    material_rate: float | None = Field(default=None, ge=0)
    labor_rate: float | None = Field(default=None, ge=0)
    durability_notes: str | None = None
    maintenance_notes: str | None = None
    suitable_regions: list[str] | None = None
    is_active: bool | None = None
    approved: bool | None = None


class MaterialOut(BaseModel):
    id: int
    name: str
    material_type: MaterialType
    description: str | None
    unit: str
    coverage_per_unit: float
    wastage_percent: float
    material_rate: float
    labor_rate: float
    durability_notes: str | None
    maintenance_notes: str | None
    suitable_regions: list | None
    is_active: bool
    approved: bool

    model_config = {"from_attributes": True}


class DesignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class DesignRegionMaterialIn(BaseModel):
    region_id: int = Field(gt=0)
    material_id: int = Field(gt=0)


class DesignOut(BaseModel):
    id: int
    project_id: int
    name: str
    is_active: bool
    redesign_path: str | None
    hq_mode: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class VisualizeRequest(BaseModel):
    design_id: int
    hq_mode: bool = False


class AreaOverrideIn(BaseModel):
    region_id: int | None = None
    region_type: RegionType
    area_sq_ft: float = Field(ge=0)
    length_ft: float | None = Field(default=None, ge=0)
    notes: str | None = None


class AreaEstimateOut(BaseModel):
    id: int
    project_id: int
    region_id: int | None
    region_type: RegionType
    area_sq_ft: float
    length_ft: float | None
    method: str | None
    confidence: float | None
    user_override: bool

    model_config = {"from_attributes": True}


class QuantityOverrideIn(BaseModel):
    quantity_line_id: int
    final_quantity: float = Field(ge=0)


class QuantityLineOut(BaseModel):
    id: int
    project_id: int
    material_id: int
    category: str
    base_quantity: float
    wastage_percent: float
    final_quantity: float
    unit: str
    user_override: bool

    model_config = {"from_attributes": True}


class RateOverrideIn(BaseModel):
    material_id: int = Field(gt=0)
    material_rate: float | None = Field(default=None, ge=0)
    labor_rate: float | None = Field(default=None, ge=0)


class CostLineOut(BaseModel):
    id: int
    project_id: int
    material_id: int | None
    category: str
    quantity: float
    unit: str
    material_rate: float
    labor_rate: float
    material_cost: float
    labor_cost: float
    total_cost: float

    model_config = {"from_attributes": True}


class CostSummaryOut(BaseModel):
    lines: list[CostLineOut]
    material_total: float
    labor_total: float
    grand_total: float
    disclaimer: str = "Advisory estimate only — not legally binding."


class ReportOut(BaseModel):
    id: int
    project_id: int
    design_id: int | None
    file_path: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ReferenceMeasurements(BaseModel):
    known_width_ft: float | None = Field(default=None, gt=0)
    known_height_ft: float | None = Field(default=None, gt=0)
    reference_object: str | None = "door"

