# Phase 01 — Database schema

- SQLAlchemy models for users, roles, projects, images, regions, materials, designs, areas, quantities, costs, reports
- Alembic migration `0001_initial`
- Seed script: roles, admin user, sample materials/rates

```bash
cd backend
source .venv/bin/activate
alembic upgrade head
python -m app.seed
```

Next: `feature/02-auth-rbac`
