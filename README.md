# AI-Based Exterior House Renovation & Cost Estimation System

Pre-construction planning platform: upload a house exterior photo, detect structure regions, apply materials, generate a redesign preview, estimate quantities/costs, and download a contractor-ready PDF report.

## Stack

| Layer | Technology |
|-------|------------|
| Frontend | Next.js, TypeScript, Tailwind CSS, Konva |
| Backend | FastAPI, SQLAlchemy, Alembic |
| Database | **PostgreSQL (native / local — no Docker)** |
| Files | Local disk (`backend/uploads/`) |
| Vision | Google Gemini |
| Redesign images | Cloudflare Workers AI (optional Gemini HQ) |
| PDF | ReportLab |

## Repository layout

```
backend/     FastAPI API
frontend/    Next.js UI
docs/        Architecture, workflows, estimation, limitations
```

## Branching

- `main` — stable / demo-ready
- `develop` — integration
- `feature/<nn>-<name>` — phase work (PR into `develop`)

## Quick start (no Docker)

### 1. Native PostgreSQL

```bash
# Install (Ubuntu/Debian) if needed
sudo apt update
sudo apt install -y postgresql postgresql-contrib

# Start service
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Create app user + database
sudo -u postgres psql <<'SQL'
CREATE USER renovation WITH PASSWORD 'renovation';
CREATE DATABASE renovation OWNER renovation;
GRANT ALL PRIVILEGES ON DATABASE renovation TO renovation;
\c renovation
GRANT ALL ON SCHEMA public TO renovation;
ALTER SCHEMA public OWNER TO renovation;
SQL
```

Test:

```bash
PGPASSWORD=renovation psql -h localhost -U renovation -d renovation -c "SELECT current_database();"
```

### 2. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# DATABASE_URL should be:
# postgresql+psycopg2://renovation:renovation@localhost:5432/renovation
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload --port 8000
```

Default admin after seed: set `ADMIN_EMAIL` + `ADMIN_PASSWORD` in the environment (not created automatically in production with a weak password).

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

## Documentation

Written deliverables for the prototype:

| Document | Contents |
|----------|----------|
| [docs/architecture.md](./docs/architecture.md) | System architecture |
| [docs/user-workflows.md](./docs/user-workflows.md) | User workflows by role |
| [docs/prototype.md](./docs/prototype.md) | How to demonstrate upload, materials, redesign, area, and cost |
| [docs/estimation-method.md](./docs/estimation-method.md) | How estimation works |
| [docs/limitations.md](./docs/limitations.md) | Limitations |

Index: [docs/README.md](./docs/README.md). Requirement mapping: [Feature_List_and_Tech_Stack.md](./Feature_List_and_Tech_Stack.md).
