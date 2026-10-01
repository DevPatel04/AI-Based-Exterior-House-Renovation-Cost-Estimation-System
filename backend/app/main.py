from pathlib import Path
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, designs, estimation, images, materials, projects, regions, reports
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.storage import ensure_upload_dirs

settings = get_settings()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    force=True,
)
for _name in (
    "app.api.regions",
    "app.api.designs",
    "app.services.gemini",
    "app.services.segformer",
    "app.services.grounded_detect",
    "app.services.cloudflare",
    "app.services.replicate_controlnet",
    "app.services.replicate_img2img",
    "app.services.replicate_nano_banana",
    "app.services.pollinations_nanobanana",
):
    logging.getLogger(_name).setLevel(logging.INFO)

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    docs_url=None if settings.environment.lower() == "production" else "/docs",
    redoc_url=None if settings.environment.lower() == "production" else "/redoc",
    openapi_url=None if settings.environment.lower() == "production" else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ensure_upload_dirs()
# Intentionally no public /files mount — serve only via authenticated API routes.

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(images.router)
app.include_router(regions.router)
app.include_router(materials.router)
app.include_router(designs.router)
app.include_router(estimation.router)
app.include_router(reports.router)


@app.get("/health")
def health():
    db_ok = False
    try:
        db = SessionLocal()
        try:
            db.execute(__import__("sqlalchemy").text("SELECT 1"))
            db_ok = True
        finally:
            db.close()
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "app": settings.app_name,
        "database": "up" if db_ok else "down",
    }
