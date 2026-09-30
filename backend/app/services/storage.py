import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings


def ensure_upload_dirs() -> Path:
    settings = get_settings()
    root = Path(settings.upload_dir)
    for sub in ("originals", "redesigns", "textures", "reports", "logos"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def save_upload(file: UploadFile, subdir: str = "originals") -> tuple[str, Path]:
    root = ensure_upload_dirs()
    suffix = Path(file.filename or "upload.bin").suffix.lower() or ".bin"
    name = f"{uuid.uuid4().hex}{suffix}"
    dest = root / subdir / name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return f"{subdir}/{name}", dest


def absolute_path(relative: str) -> Path:
    root = ensure_upload_dirs()
    return root / relative
