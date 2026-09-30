# AI-Based Exterior House Renovation & Cost Estimation System

Pre-construction planning platform: upload a house exterior photo, detect structure regions, apply materials, generate a redesign preview, estimate quantities/costs, and download a contractor-ready PDF report.

## Stack

| Layer | Technology |
|-------|------------|
| Frontend | Next.js, TypeScript, Tailwind CSS, Konva |
| Backend | FastAPI, SQLAlchemy, Alembic |
| Database | PostgreSQL |
| Files | Local disk (`backend/uploads/`) |
| Vision | Google Gemini |
| Redesign images | Cloudflare Workers AI (optional Gemini HQ) |
| PDF | ReportLab |

## Repository layout

```
backend/     FastAPI API
frontend/    Next.js UI
docs/        Architecture, workflows, estimation, limitations
docker-compose.yml
```

## Branching

- `main` — stable / demo-ready
- `develop` — integration
- `feature/<nn>-<name>` — phase work (PR into `develop`)

## Quick start

### 1. Database

```bash
docker compose up -d
```

### 2. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload --port 8000
```

### 3. Frontend

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open http://localhost:3000 — API docs at http://localhost:8000/docs

## Environment

See `backend/.env.example` and `frontend/.env.example` for Gemini, Cloudflare, and database settings.

## Security note

Never put API keys or GitHub tokens in git remotes or commits. Revoke any token that was accidentally exposed.

## Feature backlog

See [Feature_List_and_Tech_Stack.md](./Feature_List_and_Tech_Stack.md) and [docs/](./docs/).
