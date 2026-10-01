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

1. Go to [https://railway.app](https://railway.app) → **New Project**
2. **Deploy from GitHub repo** → select this repository
3. Do **not** deploy the whole monorepo as one service

## 3) Add PostgreSQL

1. In the project → **+ New** → **Database** → **PostgreSQL**
2. Open it → **Variables** → copy `DATABASE_URL` (Railway provides this)



## 4) Backend service

1. **+ New** → **GitHub Repo** (same repo) → name it `api` / `backend`
2. Settings:
  - **Root Directory:** `backend`
  - **Watch Paths:** `backend/`**
3. **Build command:**
  ```bash
   pip install -r requirements.txt
  ```
4. **Start command:**
  ```bash
   chmod +x start.sh && ./start.sh
  ```
5. **Variables** (Variables tab):


| Variable                | Value                                                          |
| ----------------------- | -------------------------------------------------------------- |
| `DATABASE_URL`          | `${{Postgres.DATABASE_URL}}` (Railway reference)               |
| `SECRET_KEY`             | long random string (32+ chars) — required outside development |
| `ADMIN_EMAIL`            | optional; only creates seed admin when set with ADMIN_PASSWORD |
| `ADMIN_PASSWORD`         | optional; never use `admin123` in production                   |
| `ENVIRONMENT`           | `production`                                                   |
| `CORS_ORIGINS`          | your frontend URL, e.g. `https://frontend-xxxx.up.railway.app` |
| `UPLOAD_DIR`            | `/data/uploads`                                                |
| `GEMINI_API_KEY`        | optional — only if you enable flags below (saves free-tier quota) |
| `ENABLE_GEMINI_QUALITY_NOTES` | `false` — upload tips use OpenCV only when off          |
| `ENABLE_GEMINI_REGION_DETECT` | `false` — use HF_TOKEN + REPLICATE for detect instead |
| `ENABLE_GEMINI_REGION_REFINE` | `false` — extra Gemini call per detect when off       |
| `CLOUDFLARE_ACCOUNT_ID` | optional                                                       |
| `CLOUDFLARE_API_TOKEN`  | optional                                                       |
| `ENABLE_GEMINI_HQ`      | `false`                                                        |
| `HF_TOKEN`              | recommended — [Hugging Face](https://huggingface.co/settings/tokens) SegFormer masks |
| `ENABLE_SEGFORMER`      | `true`                                                         |
| `SEGFORMER_MODEL`       | default `nvidia/segformer-b0-finetuned-ade-512-512`            |
| `ENABLE_DEPTH_SCALE`    | `true` (Depth Anything V2 scale when `HF_TOKEN` / Replicate set) |
| `REPLICATE_API_TOKEN`   | optional — ControlNet redesign + Grounded-SAM detect backup    |
| `ENABLE_REPLICATE_CONTROLNET` | `true` (preferred ControlNet path when token set)        |
| `REPLICATE_CONTROLNET_MODEL` | default `lucataco/sdxl-controlnet`                          |
| `REPLICATE_SEG_MODEL`   | default `schananas/grounded_sam` (per-class masks when HF fails) |
| `REPLICATE_DINO_MODEL`  | default `adirik/grounding-dino` (window/door boxes backup)      |
| `FAL_KEY`               | optional — only if you have fal credits                        |
| `ENABLE_FAL_CONTROLNET` | `true` (used when `FAL_KEY` is set; after Replicate)           |
| `FAL_CONTROLNET_MODEL`  | default `fal-ai/fast-sdxl-controlnet-canny`                    |


1. **Volume (important):** local uploads are wiped without a volume
  - Settings → **Volumes** → mount path `/data/uploads`  
  - Keep `UPLOAD_DIR=/data/uploads`
2. Generate domain: Settings → **Networking** → **Generate Domain**
  Example: `https://api-xxxx.up.railway.app`



## 5) Frontend service

1. **+ New** → same GitHub repo → name `web` / `frontend`
2. Settings:
  - **Root Directory:** `frontend`
  - **Watch Paths:** `frontend/`**
3. **Build command:**
  ```bash
   npm ci && npm run build
  ```
4. **Start command** (must bind `0.0.0.0` or Railway shows “Application failed to respond”):
  ```bash
   chmod +x start.sh && ./start.sh
  ```
   Or: `npm run start` (script already uses `--hostname 0.0.0.0 --port $PORT`)
5. **Variables:**


| Variable              | Value |
| --------------------- | ----- |
| `NEXT_PUBLIC_API_URL` | **Public** backend URL only, e.g. `https://YOUR-API.up.railway.app`. **Never** use `*.railway.internal` (browsers cannot reach it). Or leave **empty** and use the proxy below. |
| `BACKEND_URL`         | Optional. Server-side proxy target, e.g. `http://${{Backend.RAILWAY_PRIVATE_DOMAIN}}:${{Backend.PORT}}` or the same public API URL. Required if `NEXT_PUBLIC_API_URL` is empty. |
| `PORT`                | Railway sets this automatically — do not override |

**Important:** If the browser Network tab shows `*.railway.internal`, your `NEXT_PUBLIC_API_URL` is wrong. Fix it and **redeploy** the frontend (this value is baked in at build time).



1. Generate domain for frontend.



## 6) Fix CORS after frontend URL exists

In **backend** variables, set:

```text
CORS_ORIGINS=https://YOUR-FRONTEND.up.railway.app
```

Redeploy backend.

## 7) Smoke test

1. Open frontend URL
2. Register a user (or login with the admin you created via `ADMIN_EMAIL` / `ADMIN_PASSWORD`)
3. Create project → upload image → detect → materials → redesign → estimate → PDF

API docs: `https://YOUR-API.up.railway.app/docs`

## Things that must change for production


| Item                     | Why                                                           |
| ------------------------ | ------------------------------------------------------------- |
| `SECRET_KEY`             | Security                                                      |
| `DATABASE_URL`           | Use Railway Postgres, not local                               |
| `CORS_ORIGINS`           | Must match frontend HTTPS URL                                 |
| `NEXT_PUBLIC_API_URL`    | Browser calls API on Railway                                  |
| `UPLOAD_DIR` + Volume    | Files persist across deploys                                  |
| Default admin            | Only if `ADMIN_EMAIL` + `ADMIN_PASSWORD` are set              |
| Gemini / Cloudflare keys | Needed for real AI; without them redesign uses local fallback |
| Branch                   | Deploy from `develop` or synced `main`                        |




## Common Railway failures

- **Application failed to respond:** app not listening on `0.0.0.0:$PORT` (frontend: use `./start.sh` / `npm run start`; backend: `./start.sh`). Also check deploy logs for crash on boot (migrate/DB).
- **Register/API calls go to `*.railway.internal`:** set `NEXT_PUBLIC_API_URL` to the backend **public** `https://…up.railway.app` URL (or leave empty + set `BACKEND_URL` for proxy), then redeploy frontend.
- **Seed / roles DatatypeMismatch:** ORM must use native PG enums (fixed); redeploy backend so seed inserts succeed.
- **DB connection error:** ensure backend has `DATABASE_URL` from Postgres plugin; app auto-converts `postgres://` → `postgresql+psycopg2://`
- **CORS blocked:** frontend URL missing from `CORS_ORIGINS` (not needed if using same-origin proxy)
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

