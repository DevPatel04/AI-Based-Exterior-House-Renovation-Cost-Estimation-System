import base64
import uuid
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from app.core.config import get_settings
from app.services.storage import ensure_upload_dirs


async def generate_redesign(
    source_path: Path,
    prompt: str,
    hq_mode: bool = False,
) -> tuple[str, str]:
    """
    Returns (relative_path, engine_used).
    Tries Cloudflare Workers AI, optional Gemini HQ, then local PIL fallback.
    """
    settings = get_settings()
    if hq_mode and settings.enable_gemini_hq and settings.gemini_api_key:
        path = await _gemini_hq(source_path, prompt)
        if path:
            return path, "gemini_hq"

    if settings.cloudflare_account_id and settings.cloudflare_api_token:
        path = await _cloudflare_img2img(source_path, prompt)
        if path:
            return path, "cloudflare"

    return _local_fallback_redesign(source_path, prompt), "local_fallback"


async def _cloudflare_img2img(source_path: Path, prompt: str) -> str | None:
    settings = get_settings()
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{settings.cloudflare_account_id}"
        f"/ai/run/{settings.cloudflare_image_model}"
    )
    try:
        img = Image.open(source_path).convert("RGB")
        img.thumbnail((1024, 1024))
        import io

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_b64 = base64.b64encode(buf.getvalue()).decode()

        payload = {
            "prompt": prompt,
            "image_b64": image_b64,
            "strength": 0.45,
            "num_steps": 8,
        }
        headers = {"Authorization": f"Bearer {settings.cloudflare_api_token}"}
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                return None
            content_type = resp.headers.get("content-type", "")
            root = ensure_upload_dirs()
            name = f"{uuid.uuid4().hex}.png"
            dest = root / "redesigns" / name
            if "image" in content_type:
                dest.write_bytes(resp.content)
            else:
                data = resp.json()
                # Some CF models return base64 in JSON
                result = data.get("result")
                if isinstance(result, str):
                    dest.write_bytes(base64.b64decode(result))
                elif isinstance(result, dict) and "image" in result:
                    dest.write_bytes(base64.b64decode(result["image"]))
                else:
                    return None
            return f"redesigns/{name}"
    except Exception:
        return None


async def _gemini_hq(source_path: Path, prompt: str) -> str | None:
    settings = get_settings()
    try:
        import google.generativeai as genai

        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel(settings.gemini_image_model)
        uploaded = genai.upload_file(str(source_path))
        result = model.generate_content([uploaded, prompt])
        # Response formats vary; try to find inline image bytes
        root = ensure_upload_dirs()
        name = f"{uuid.uuid4().hex}.png"
        dest = root / "redesigns" / name
        for cand in getattr(result, "candidates", []) or []:
            content = getattr(cand, "content", None)
            for part in getattr(content, "parts", []) or []:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    dest.write_bytes(inline.data)
                    return f"redesigns/{name}"
        return None
    except Exception:
        return None


def _local_fallback_redesign(source_path: Path, prompt: str) -> str:
    """Deterministic visual change so demos work without cloud AI keys."""
    root = ensure_upload_dirs()
    name = f"{uuid.uuid4().hex}.jpg"
    dest = root / "redesigns" / name
    img = Image.open(source_path).convert("RGB")
    enhancer = ImageEnhance.Color(img)
    img = enhancer.enhance(1.25)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.1)
    img = img.filter(ImageFilter.SMOOTH_MORE)
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    # Soft facade tint band suggesting new cladding/paint
    draw.rectangle([int(w * 0.12), int(h * 0.22), int(w * 0.88), int(h * 0.82)], fill=(180, 140, 100, 55))
    draw.rectangle([int(w * 0.12), int(h * 0.22), int(w * 0.88), int(h * 0.28)], fill=(90, 90, 90, 80))
    img.save(dest, quality=92)
    return f"redesigns/{name}"
