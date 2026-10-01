import io
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from PIL import Image, UnidentifiedImageError

from app.core.config import get_settings

MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def ensure_upload_dirs() -> Path:
    settings = get_settings()
    root = Path(settings.upload_dir)
    for sub in ("originals", "redesigns", "textures", "reports", "logos"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def _normalize_image_bytes(data: bytes, max_edge: int = 1600) -> tuple[bytes, str]:
    """Decode any Pillow image, downscale large photos, store as JPEG/PNG/WebP/GIF."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = (img.format or "").upper()
            img.load()
            w, h = img.size
            needs_resize = max(w, h) > max_edge > 0
            # Keep GIF as-is (animation); otherwise downscale + recompress for speed
            if fmt == "GIF" and not needs_resize:
                return data, ".gif"
            rgb = img.convert("RGB") if img.mode not in ("RGB", "L") else img.convert("RGB")
            if needs_resize:
                rgb.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            if fmt == "PNG" and not needs_resize and len(data) < 2_000_000:
                return data, ".png"
            # JPEG is much faster for detect/redesign uploads than huge PNG/HEIC
            rgb.save(out, format="JPEG", quality=85, optimize=True)
            return out.getvalue(), ".jpg"
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise HTTPException(status_code=400, detail="Could not read that file as an image") from None


def _write_normalized(data: bytes, subdir: str) -> tuple[str, Path]:
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image is too large (max 15 MB)")
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")
    max_edge = int(get_settings().upload_max_edge or 1600)
    normalized, ext = _normalize_image_bytes(data, max_edge=max_edge)
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
