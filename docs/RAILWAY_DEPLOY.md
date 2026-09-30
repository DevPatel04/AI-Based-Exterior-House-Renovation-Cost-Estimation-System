# Deploy on Railway (monorepo)

This app needs **3 Railway resources**:
1. PostgreSQL
2. Backend (FastAPI) — root `backend/`
3. Frontend (Next.js) — root `frontend/`

## 1) Push code to GitHub

Use branch `develop` (or `main` after you sync it).

```bash
git checkout develop
git push origin develop
```

## 2) Create Railway project

1. Go to https://railway.app → **New Project**
2. **Deploy from GitHub repo** → select this repository
3. Do **not** deploy the whole monorepo as one service

## 3) Add PostgreSQL

1. In the project → **+ New** → **Database** → **PostgreSQL**
2. Open it → **Variables** → copy `DATABASE_URL` (Railway provides this)

## 4) Backend service

1. **+ New** → **GitHub Repo** (same repo) → name it `api` / `backend`
2. Settings:
   - **Root Directory:** `backend`
   - **Watch Paths:** `backend/**`
3. **Build command:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Start command:**
   ```bash
   chmod +x start.sh && ./start.sh
   ```
5. **Variables** (Variables tab):

| Variable | Value |
|----------|--------|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (Railway reference) |
| `SECRET_KEY` | long random string |
| `ENVIRONMENT` | `production` |
| `CORS_ORIGINS` | your frontend URL, e.g. `https://frontend-xxxx.up.railway.app` |
| `UPLOAD_DIR` | `/data/uploads` |
| `GEMINI_API_KEY` | optional |
| `CLOUDFLARE_ACCOUNT_ID` | optional |
| `CLOUDFLARE_API_TOKEN` | optional |
| `ENABLE_GEMINI_HQ` | `false` |

6. **Volume (important):** local uploads are wiped without a volume  
   - Settings → **Volumes** → mount path `/data/uploads`  
   - Keep `UPLOAD_DIR=/data/uploads`

7. Generate domain: Settings → **Networking** → **Generate Domain**  
   Example: `https://api-xxxx.up.railway.app`

## 5) Frontend service

1. **+ New** → same GitHub repo → name `web` / `frontend`
2. Settings:
   - **Root Directory:** `frontend`
   - **Watch Paths:** `frontend/**`
3. **Build command:**
   ```bash
   npm ci && npm run build
   ```
4. **Start command:**
   ```bash
   npm run start -- -p $PORT
   ```
5. **Variables:**

| Variable | Value |
|----------|--------|
| `NEXT_PUBLIC_API_URL` | your backend public URL, e.g. `https://api-xxxx.up.railway.app` |
| `PORT` | Railway sets this automatically |

6. Generate domain for frontend.

## 6) Fix CORS after frontend URL exists

In **backend** variables, set:

```text
CORS_ORIGINS=https://YOUR-FRONTEND.up.railway.app
```

Redeploy backend.

## 7) Smoke test

1. Open frontend URL  
2. Register a user (or login seed admin if seeded: `admin@renovation.local` / `admin123` — **change password immediately**)  
3. Create project → upload image → detect → materials → redesign → estimate → PDF  

API docs: `https://YOUR-API.up.railway.app/docs`

## Things that must change for production

| Item | Why |
|------|-----|
| `SECRET_KEY` | Security |
| `DATABASE_URL` | Use Railway Postgres, not local |
| `CORS_ORIGINS` | Must match frontend HTTPS URL |
| `NEXT_PUBLIC_API_URL` | Browser calls API on Railway |
| `UPLOAD_DIR` + Volume | Files persist across deploys |
| Default admin password | Seed creates `admin123` — change it |
| Gemini / Cloudflare keys | Needed for real AI; without them redesign uses local fallback |
| Branch | Deploy from `develop` or synced `main` |

## Common Railway failures

- **DB connection error:** ensure backend has `DATABASE_URL` from Postgres plugin; app auto-converts `postgres://` → `postgresql+psycopg2://`
- **CORS blocked:** frontend URL missing from `CORS_ORIGINS`
- **Images disappear after redeploy:** no volume on `/data/uploads`
- **Frontend calls localhost:** `NEXT_PUBLIC_API_URL` not set at **build** time (set before build / redeploy)
- **Wrong root:** monorepo must use Root Directory `backend` / `frontend`

## Optional: one command checklist

```text
[ ] GitHub repo connected
[ ] Postgres added
[ ] Backend root=backend, start=./start.sh
[ ] Backend DATABASE_URL + SECRET_KEY + CORS + volume
[ ] Frontend root=frontend, NEXT_PUBLIC_API_URL=backend URL
[ ] Both public domains generated
[ ] CORS updated with frontend domain
[ ] Test /health and login
```
