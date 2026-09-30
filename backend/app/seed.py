"""Seed roles, admin user, and sample materials/rates."""

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import Material, MaterialType, Role, RoleName, User, UserRole


ROLE_DEFS = [
    (RoleName.homeowner, "Individual homeowner planning renovation"),
    (RoleName.contractor, "Contractor reviewing designs and quotes"),
    (RoleName.architect, "Architect advising on design"),
    (RoleName.builder, "Builder checking quantities and labor"),
    (RoleName.consultant, "Real estate consultant supporting clients"),
    (RoleName.supplier, "Material supplier managing catalog"),
    (RoleName.admin, "System administrator"),
]

MATERIALS = [
    {
        "name": "Premium Exterior Emulsion - Warm White",
        "material_type": MaterialType.paint,
        "unit": "liter",
        "coverage_per_unit": 80.0,
        "wastage_percent": 10.0,
        "material_rate": 320.0,
        "labor_rate": 12.0,
        "suitable_regions": ["main_wall", "parapet", "pillar"],
        "durability_notes": "5–7 years typical",
        "maintenance_notes": "Washable; recoating recommended after monsoon wear",
    },
    {
        "name": "Natural Stone Cladding - Sandstone",
        "material_type": MaterialType.stone_cladding,
        "unit": "sq_ft",
        "coverage_per_unit": 1.0,
        "wastage_percent": 12.0,
        "material_rate": 180.0,
        "labor_rate": 45.0,
        "suitable_regions": ["main_wall", "pillar", "gate"],
        "durability_notes": "High durability",
        "maintenance_notes": "Seal every 2–3 years",
    },
    {
        "name": "Ceramic Facade Tiles - Grey",
        "material_type": MaterialType.tiles,
        "unit": "sq_ft",
        "coverage_per_unit": 1.0,
        "wastage_percent": 10.0,
        "material_rate": 95.0,
        "labor_rate": 35.0,
        "suitable_regions": ["main_wall", "balcony"],
    },
    {
        "name": "Texture Finish - Rough Cast",
        "material_type": MaterialType.texture_finish,
        "unit": "sq_ft",
        "coverage_per_unit": 1.0,
        "wastage_percent": 8.0,
        "material_rate": 40.0,
        "labor_rate": 25.0,
        "suitable_regions": ["main_wall", "parapet"],
    },
    {
        "name": "Glass Railing - Clear Tempered",
        "material_type": MaterialType.glass_railing,
        "unit": "sq_ft",
        "coverage_per_unit": 1.0,
        "wastage_percent": 5.0,
        "material_rate": 450.0,
        "labor_rate": 120.0,
        "suitable_regions": ["balcony", "railing", "roof_edge"],
    },
    {
        "name": "MS Metal Railing - Powder Coated",
        "material_type": MaterialType.metal_railing,
        "unit": "sq_ft",
        "coverage_per_unit": 1.0,
        "wastage_percent": 5.0,
        "material_rate": 220.0,
        "labor_rate": 80.0,
        "suitable_regions": ["balcony", "railing", "gate"],
    },
    {
        "name": "ACP Panels - Charcoal",
        "material_type": MaterialType.panels,
        "unit": "sq_ft",
        "coverage_per_unit": 1.0,
        "wastage_percent": 10.0,
        "material_rate": 160.0,
        "labor_rate": 55.0,
        "suitable_regions": ["main_wall", "parapet"],
    },
]


def seed() -> None:
    from app.core.config import get_settings

    settings = get_settings()
    db = SessionLocal()
    try:
        for name, desc in ROLE_DEFS:
            if not db.query(Role).filter(Role.name == name).first():
                db.add(Role(name=name, description=desc))
        db.commit()

        admin_email = (settings.admin_email or "").strip().lower()
        admin_password = (settings.admin_password or "").strip()
        legacy_email = "admin@renovation.local"

        # Migrate legacy seed email if present
        if admin_email:
            legacy = db.query(User).filter(User.email == legacy_email).first()
            if legacy and not db.query(User).filter(User.email == admin_email).first():
                legacy.email = admin_email
                db.commit()
                print(f"Migrated admin email {legacy_email} → {admin_email}")

        if admin_email and admin_password:
            if settings.environment.lower() not in {"development", "dev", "test", "local"} and admin_password in {
                "admin123",
                "password",
                "changeme",
            }:
                print("Skipping admin seed: weak ADMIN_PASSWORD not allowed outside development")
            else:
                admin = db.query(User).filter(User.email == admin_email).first()
                if not admin:
                    admin = User(
                        email=admin_email,
                        hashed_password=hash_password(admin_password),
                        full_name="System Admin",
                        company="House Renovation Platform",
                    )
                    db.add(admin)
                    db.flush()
                    admin_role = db.query(Role).filter(Role.name == RoleName.admin).first()
                    if admin_role:
                        db.add(UserRole(user_id=admin.id, role_id=admin_role.id))
                    db.commit()
                    print(f"Created admin user: {admin_email}")
                else:
                    print("Admin user already exists")
        else:
            print("Skipping admin seed (set ADMIN_EMAIL and ADMIN_PASSWORD to create one)")

        if db.query(Material).count() == 0:
            for m in MATERIALS:
                db.add(Material(**m, approved=True, is_active=True))
            db.commit()
            print(f"Seeded {len(MATERIALS)} materials")
        else:
            print("Materials already seeded")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
