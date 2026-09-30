from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import auth, images, projects
from app.core.config import get_settings

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.services.storage import ensure_upload_dirs

ensure_upload_dirs()
upload_root = Path(settings.upload_dir)
app.mount("/files", StaticFiles(directory=str(upload_root)), name="files")

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(images.router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "phase": "04-upload-quality",
    }
