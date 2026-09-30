from app.models import RoleName

# Permission keys used by API dependencies
PERMISSIONS: dict[str, set[str]] = {
    "project:create": {
        RoleName.homeowner.value,
        RoleName.contractor.value,
        RoleName.architect.value,
        RoleName.consultant.value,
        RoleName.admin.value,
    },
    "project:edit": {
        RoleName.homeowner.value,
        RoleName.contractor.value,
        RoleName.architect.value,
        RoleName.builder.value,
        RoleName.consultant.value,
        RoleName.admin.value,
    },
    "regions:edit": {
        RoleName.homeowner.value,
        RoleName.contractor.value,
        RoleName.architect.value,
        RoleName.builder.value,
        RoleName.consultant.value,
        RoleName.admin.value,
    },
    "materials:select": {
        RoleName.homeowner.value,
        RoleName.contractor.value,
        RoleName.architect.value,
        RoleName.consultant.value,
        RoleName.admin.value,
    },
    "materials:manage": {
        RoleName.supplier.value,
        RoleName.admin.value,
    },
    "materials:approve": {RoleName.admin.value},
    "areas:override": {
        RoleName.contractor.value,
        RoleName.architect.value,
        RoleName.builder.value,
        RoleName.admin.value,
    },
    "quantities:override": {
        RoleName.contractor.value,
        RoleName.builder.value,
        RoleName.admin.value,
    },
    "rates:edit": {
        RoleName.homeowner.value,
        RoleName.contractor.value,
        RoleName.builder.value,
        RoleName.admin.value,
    },
    "rates:manage_defaults": {
        RoleName.supplier.value,
        RoleName.admin.value,
    },
    "users:manage": {RoleName.admin.value},
    "report:download": {
        RoleName.homeowner.value,
        RoleName.contractor.value,
        RoleName.architect.value,
        RoleName.builder.value,
        RoleName.consultant.value,
        RoleName.admin.value,
    },
    "visualize:generate": {
        RoleName.homeowner.value,
        RoleName.contractor.value,
        RoleName.architect.value,
        RoleName.consultant.value,
        RoleName.admin.value,
    },
}


def user_has_permission(role_names: list[str], permission: str) -> bool:
    allowed = PERMISSIONS.get(permission, set())
    return any(r in allowed for r in role_names)
