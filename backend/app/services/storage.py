import io
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from PIL import Image, UnidentifiedImageError

from app.core.config import get_settings

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
KEEP_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}


def ensure_upload_dirs() -> Path:
    settings = get_settings()
    root = Path(settings.upload_dir)
    for sub in ("originals", "redesigns", "textures", "reports", "logos"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def _normalize_image_bytes(data: bytes) -> tuple[bytes, str]:
    """Accept any image Pillow can decode; store as jpg/png/webp/gif or convert to JPEG."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = (img.format or "").upper()
            img.load()
            if fmt in KEEP_EXTENSIONS:
                return data, KEEP_EXTENSIONS[fmt]
            rgb = img.convert("RGB")
            out = io.BytesIO()
            rgb.save(out, format="JPEG", quality=92)
            return out.getvalue(), ".jpg"
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise HTTPException(status_code=400, detail="Could not read that file as an image") from None


def _write_normalized(data: bytes, subdir: str) -> tuple[str, Path]:
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image is too large (max 15 MB)")
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")
    normalized, ext = _normalize_image_bytes(data)
    root = ensure_upload_dirs()
    name = f"{uuid.uuid4().hex}{ext}"
    dest = root / subdir / name
    dest.write_bytes(normalized)
    return f"{subdir}/{name}", dest


def save_upload(file: UploadFile, subdir: str = "originals") -> tuple[str, Path]:
    """Sync upload helper — accepts any image format Pillow can open."""
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    return _write_normalized(data, subdir)


async def save_image_upload(file: UploadFile, subdir: str) -> tuple[str, Path]:
    """Async upload helper — accepts any image format Pillow can open."""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    return await run_in_threadpool(_write_normalized, data, subdir)


def absolute_path(relative: str) -> Path:
    root = ensure_upload_dirs().resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(status_code=404, detail="File not found")
    return path
