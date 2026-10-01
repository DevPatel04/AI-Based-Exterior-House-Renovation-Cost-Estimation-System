# System architecture

FacadePlan is a pre-construction assistant for exterior renovation of low-rise houses. A user uploads a facade photo, reviews detected surfaces, applies catalog materials, generates a redesign of that photo, and receives an advisory area, quantity, and cost estimate plus a PDF report.

It is a two-application monorepo. The browser talks only to the API. AI providers are called from the backend.

```
Browser (Next.js)
    │  REST + JWT
FastAPI
    ├── PostgreSQL          projects, regions, materials, designs, estimates
    ├── Local disk          originals, redesigns, textures, PDF reports
    ├── Gemini vision       structure boxes, material suggestions, quantity survey
    ├── Gemini image models redesign of the uploaded photo (primary)
    ├── Optional backups    SegFormer / Grounded-SAM for detection;
    │                       Cloudflare Workers AI for redesign;
    │                       Depth Anything V2 when Gemini sizing is unavailable
    └── ReportLab           contractor discussion PDF
```

## Runtime components

| Component | Responsibility |
|-----------|----------------|
| `frontend/` | Login, dashboard, six-step project wizard, Konva region editor, before/after view, catalog, admin |
| `backend/app/api` | Auth, projects, images, regions, materials, designs, estimation, reports |
| `backend/app/services` | Storage, quality hints, detection, material prompts, redesign, area and cost rules, PDF |
| `backend/alembic` | Schema migrations |
| PostgreSQL | System of record. File bytes are not stored in the database. |
| `backend/uploads/` | Originals, redesigns, material textures, reports. Served only through authenticated routes. |

There is no public file mount. Image and PDF downloads go through API routes that check project access.

## Request path

1. The Next.js app stores a JWT and calls `/api/...`.
2. FastAPI validates the token and a permission key for the caller’s roles.
3. Project data is read and written with SQLAlchemy.
4. Uploaded and generated images are written under `uploads/` and referenced by relative path.
5. Long vision and image-generation calls run off the request thread via a thread pool so the event loop stays free.

## Data model

| Entity | Holds |
|--------|--------|
| User, Role, UserRole | Account and one or more of homeowner, contractor, architect, builder, consultant, supplier, admin |
| Project, ProjectMember | Owner, status (`draft`, `designed`, `estimated`, `reported`), optional share as editor or viewer |
| ProjectImage | Stored path, dimensions, primary flag, quality message |
| StructureRegion | Type, label, normalized polygon (`x`/`y` in 0–1), confidence, source engine |
| Material, MaterialTexture | Catalog row: type, unit, coverage, wastage %, material rate, labor rate, suitable regions, optional texture |
| Design, DesignRegionMaterial | A named material scheme and the region → material map |
| AreaEstimate | Area (sq ft), optional length (ft), method, confidence, user-override flag |
| QuantityLine, CostLine, RateOverride | Purchase quantity and the material/labor cost lines for the active design |
| Report | Generated PDF path |

Region types: main wall, window, balcony, pillar, parapet, gate, roof edge, railing, other.

Material types: paint, stone cladding, tiles, texture finish, glass railing, metal railing, panels, other.

## API surface

All project routes are under `/api` and require a bearer token, except register and login.

| Area | Main operations |
|------|-----------------|
| Auth | Register, login, current user, profile |
| Projects | Create, list, open, share, archive |
| Images | Upload, list, set primary, delete, download |
| Regions | Detect, list, create, update, delete, clear |
| Materials | List catalog, supplier create/edit, admin approve |
| Designs | Create variant, assign materials, suggest materials, visualize, download redesign |
| Estimation | Estimate areas, override area, calculate costs, override quantity, set rates |
| Reports | Generate PDF, list, download |

Interactive OpenAPI is at `/docs` when `ENVIRONMENT` is not `production`.

## Image upload

`POST /api/projects/{id}/images` accepts the file, stores it under `uploads/originals/`, and records width and height. OpenCV then adds soft quality notes (resolution, blur, brightness). Those notes never reject the upload. Optional Gemini quality sentences run only when `ENABLE_GEMINI_QUALITY_NOTES` is true. The first image on a project becomes primary. Later uploads can be marked primary. Downstream detection, redesign, and estimation use the primary image.

## Structure detection

`POST /api/projects/{id}/regions/detect` runs `detect_structure_regions` on the primary photo. Engines are tried in this order and merged when the earlier result is thin:

1. **Gemini vision** (`GEMINI_DETECT_MODEL`, default `gemini-2.5-flash`) returns tight boxes for wall, window, gate, balcony, roof edge, railing, pillar, and parapet. Boxes are normalized polygons. Signs, people, vehicles, and duplicate openings are excluded by the prompt. OpenCV is added only when Gemini finds fewer than two windows and no door.
2. **SegFormer** on Hugging Face, if `HF_TOKEN` is set and more openings are still needed.
3. **Grounded-SAM** on Replicate, if `REPLICATE_API_TOKEN` is set and openings are still scarce.
4. **OpenCV-only** fallback when no model returned regions.

Manual regions are kept. A new detect replaces auto-detected regions only. The user can draw, move, relabel, and delete polygons in the Konva canvas. Corrected polygons are what later steps measure and paint.

## Material application

A project can hold several designs. One is active. Each design stores a set of `DesignRegionMaterial` rows: one catalog material per region.

Suggestions (`material_suggest`) ask Gemini to pick one approved catalog material per region from the photo, preferring a consistent wall finish. If Gemini is unavailable, a rule table maps region type to material type (paint or cladding for walls, metal or glass for railings and gates, and so on) and takes the first matching active material.

Saving assignments replaces the previous map for that design. Visualize refuses to run until at least one valid region–material pair is saved.

## Redesign

`POST /api/projects/{id}/designs/visualize` builds a prompt from the saved assignments (region label, polygon, material name, type, description, optional texture) and an optional scene description of the uploaded photo. `generate_redesign` then:

1. Calls Gemini image models (Nano Banana family). Default model is `GEMINI_IMAGE_MODEL` (`gemini-2.5-flash-image`), with `GEMINI_IMAGE_FALLBACK_MODEL` and `GEMINI_IMAGE_LEGACY_MODEL` tried in order. High-quality mode prefers the stronger models first.
2. If Gemini fails and `ENABLE_CLOUDFLARE_REDESIGN` is true, tries Cloudflare Workers AI.
3. If both fail, returns HTTP 503. A painted-box fallback is not used (`ALLOW_LOCAL_REDESIGN_FALLBACK` defaults to false).

The generated image is resized to the source photo so the before/after comparison lines up, stored under `uploads/`, and linked on the design. The project status becomes `designed`.

## Estimation services

Area and cost logic lives in `estimation.py` and `ai_estimate.py`. The API sequence is:

1. `POST .../estimation/areas` — Gemini quantity-survey pass for facade size and per-region area. If that fails, Depth Anything V2 or the user’s width/height, then polygon area times facade size.
2. `POST .../estimation/calculate` — quantities from the active design’s materials, then material and labor cost. Gemini quantities are preferred; coverage and wastage formulas are the fallback.

User overrides of area, quantity, and rates are preserved and win over the next automatic pass. Details and formulas are in [estimation-method.md](./estimation-method.md).

## Report

`reports` assembles a ReportLab PDF: project summary, before and after images, materials by region, quantity schedule, cost breakdown in INR, and an advisory disclaimer. Status becomes `reported`.

## Security

- Passwords are hashed with bcrypt. Sessions are JWT bearer tokens.
- Mutating routes check permission keys (`project:edit`, `materials:select`, `areas:override`, `rates:edit`, and others) against the caller’s roles. Sharing a project grants access; it does not bypass those keys.
- Uploads are image files decoded by Pillow/OpenCV. Paths stay on local disk and are not exposed as a static directory.
- In non-development environments the API refuses to start with a short or placeholder `SECRET_KEY`.
- Provider keys stay in environment variables and are not returned to the browser.

## Configuration that changes behavior

| Variable | Effect |
|----------|--------|
| `DATABASE_URL` | PostgreSQL connection |
| `GEMINI_API_KEY` | Required for AI detect, suggestions, redesign, and AI estimates |
| `GEMINI_DETECT_MODEL` | Vision model for structure boxes |
| `GEMINI_IMAGE_MODEL` and fallbacks | Image-edit models for redesign |
| `ENABLE_GEMINI_REDESIGN` / `ENABLE_GEMINI_HQ` | Turn redesign and higher-quality model order on or off |
| `HF_TOKEN`, `ENABLE_SEGFORMER`, `ENABLE_DEPTH_SCALE` | Optional detection and depth scale |
| `REPLICATE_API_TOKEN` | Optional Grounded-SAM when openings are missing |
| `ENABLE_CLOUDFLARE_REDESIGN` | Optional redesign backup (off by default) |
| `ALLOW_LOCAL_REDESIGN_FALLBACK` | Keep false so a failed AI call does not return a flat color mock |

## Deployment shape

Run PostgreSQL, `alembic upgrade head`, `python -m app.seed`, then `uvicorn` for the API and `next start` for the UI. Put both behind a reverse proxy. Point `CORS_ORIGINS` at the frontend origin. Uploads must live on a persistent disk if the API is restarted or moved.
