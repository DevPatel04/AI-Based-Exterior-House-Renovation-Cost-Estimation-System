# System architecture

## Overview

FacadePlan is a monorepo pre-construction assistant for exterior house renovation.

```
Browser (Next.js)
    │ REST + JWT
FastAPI backend
    ├── Native PostgreSQL (projects, roles, materials, estimates)
    ├── Local disk uploads/ (originals, redesigns, reports)
    ├── Gemini (vision / optional HQ image)
    └── Cloudflare Workers AI (redesign img2img)
```

## Components

| Component | Responsibility |
|-----------|----------------|
| `frontend/` | Role-aware wizard UI, Konva region review, before/after |
| `backend/app/api` | Auth, projects, images, regions, materials, designs, estimation, reports |
| `backend/app/services` | Storage, OpenCV quality, Gemini, Cloudflare, estimation rules, ReportLab |
| `backend/alembic` | Schema migrations |
| Native PostgreSQL | Primary database (no Docker) |

## Security

- Passwords hashed with bcrypt
- JWT bearer tokens
- RBAC permission checks on mutating endpoints
- Uploads constrained to image content types; files stored outside DB

## Deployment notes

- Set `SECRET_KEY`, `DATABASE_URL`, `GEMINI_API_KEY`, Cloudflare credentials in `.env`
- Run `alembic upgrade head` then `python -m app.seed`
- Serve frontend (`next start`) and API (`uvicorn`) behind reverse proxy in production
