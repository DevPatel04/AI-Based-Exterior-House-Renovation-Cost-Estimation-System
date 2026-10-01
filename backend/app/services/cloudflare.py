import base64
import hashlib
import logging
import uuid
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from app.core.config import get_settings
from app.services.storage import ensure_upload_dirs

logger = logging.getLogger(__name__)


async def generate_redesign(
    source_path: Path,
    prompt: str,
    hq_mode: bool = False,
) -> tuple[str, str, list[str]]:
    """
    Returns (relative_path, engine_used, failure_notes).

    Order:
      1) Gemini HQ (only when hq_mode + keys)
      2) Replicate SDXL ControlNet (REPLICATE_API_TOKEN)
      3) fal.ai ControlNet Canny (optional FAL_KEY)
      4) Cloudflare Workers AI img2img
      5) Local PIL fallback (only if ALLOW_LOCAL_REDESIGN_FALLBACK=true)
    """
    settings = get_settings()
    notes: list[str] = []
    logger.info(
        "REDESIGN begin hq=%s replicate=%s fal=%s cloudflare=%s local_ok=%s",
        hq_mode,
        bool((settings.replicate_api_token or "").strip() and settings.enable_replicate_controlnet),
        bool((settings.fal_key or "").strip() and settings.enable_fal_controlnet),
        bool(settings.cloudflare_account_id and settings.cloudflare_api_token),
        bool(getattr(settings, "allow_local_redesign_fallback", False)),
    )

    if hq_mode and settings.enable_gemini_hq and settings.gemini_api_key:
        logger.info("REDESIGN try gemini_hq")
        path = await _gemini_hq(source_path, prompt)
        if path:
            logger.info("REDESIGN ok engine=gemini_hq path=%s", path)
            return path, "gemini_hq", notes
        notes.append("gemini_hq: no image in response")
        logger.warning("REDESIGN fail gemini_hq")
    elif hq_mode:
        notes.append("gemini_hq: skipped (ENABLE_GEMINI_HQ or GEMINI_API_KEY missing)")

    if settings.enable_replicate_controlnet and (settings.replicate_api_token or "").strip():
        from app.services.replicate_controlnet import generate_replicate_controlnet_redesign

        logger.info("REDESIGN try replicate_controlnet")
        path, err = await generate_replicate_controlnet_redesign(source_path, prompt)
        if path:
            logger.info("REDESIGN ok engine=replicate_controlnet path=%s", path)
            return path, "replicate_controlnet", notes
        notes.append(f"replicate_controlnet: {err or 'failed'}")
        logger.warning("REDESIGN fail replicate_controlnet err=%s", err)
    else:
        notes.append("replicate_controlnet: skipped (REPLICATE_API_TOKEN missing or disabled)")

    if settings.enable_fal_controlnet and (settings.fal_key or "").strip():
        from app.services.fal_controlnet import generate_fal_controlnet_redesign

        logger.info("REDESIGN try fal_controlnet")
        path = await generate_fal_controlnet_redesign(source_path, prompt)
        if path:
            logger.info("REDESIGN ok engine=fal_controlnet path=%s", path)
            return path, "fal_controlnet", notes
        notes.append("fal_controlnet: request failed")
        logger.warning("REDESIGN fail fal_controlnet")
    else:
        notes.append("fal_controlnet: skipped (FAL_KEY missing or disabled)")

    if settings.cloudflare_account_id and settings.cloudflare_api_token:
        logger.info("REDESIGN try cloudflare")
        path = await _cloudflare_img2img(source_path, prompt)
        if path:
            logger.info("REDESIGN ok engine=cloudflare path=%s", path)
            return path, "cloudflare", notes
        notes.append("cloudflare: request failed")
        logger.warning("REDESIGN fail cloudflare")
    else:
        notes.append("cloudflare: skipped (CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN missing)")

    if settings.allow_local_redesign_fallback:
        path = _local_fallback_redesign(source_path, prompt)
        logger.warning("REDESIGN local_fallback path=%s notes=%s", path, notes)
        return path, "local_fallback", notes

    logger.error("REDESIGN unavailable notes=%s", notes)
    raise RedesignUnavailableError(notes)


class RedesignUnavailableError(Exception):
    """All AI redesign engines failed and local fallback is disabled."""

    def __init__(self, notes: list[str]):
        self.notes = notes
        super().__init__("; ".join(notes) if notes else "No redesign engine available")


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
                logger.warning("REDESIGN cloudflare http=%s body=%s", resp.status_code, resp.text[:200])
                return None
            content_type = resp.headers.get("content-type", "")
            root = ensure_upload_dirs()
            name = f"{uuid.uuid4().hex}.png"
            dest = root / "redesigns" / name
            if "image" in content_type:
                dest.write_bytes(resp.content)
            else:
                data = resp.json()
                result = data.get("result")
                if isinstance(result, str):
                    dest.write_bytes(base64.b64decode(result))
                elif isinstance(result, dict) and "image" in result:
                    dest.write_bytes(base64.b64decode(result["image"]))
                else:
                    return None
            return f"redesigns/{name}"
    except Exception as exc:
        logger.warning("REDESIGN cloudflare exception: %s", exc)
        return None


async def _gemini_hq(source_path: Path, prompt: str) -> str | None:
    from fastapi.concurrency import run_in_threadpool

    def _run() -> str | None:
        settings = get_settings()
        try:
            import google.generativeai as genai

            genai.configure(api_key=settings.gemini_api_key)
            model = genai.GenerativeModel(settings.gemini_image_model)
            uploaded = genai.upload_file(str(source_path))
            result = model.generate_content([uploaded, prompt])
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
        except Exception as exc:
            logger.warning("REDESIGN gemini_hq exception: %s", exc)
            return None

    return await run_in_threadpool(_run)


def _local_fallback_redesign(source_path: Path, prompt: str) -> str:
    """Deterministic, prompt-dependent visual change so Design A vs B differ without AI keys."""
    root = ensure_upload_dirs()
    name = f"{uuid.uuid4().hex}.jpg"
    dest = root / "redesigns" / name
    img = Image.open(source_path).convert("RGB")

    digest = hashlib.sha256((prompt or "default").encode("utf-8")).digest()
    r, g, b = digest[0], digest[1], digest[2]
    accent = (40 + (r % 180), 40 + (g % 180), 40 + (b % 180), 70 + (digest[3] % 50))
    band = (30 + (digest[4] % 100), 30 + (digest[5] % 100), 30 + (digest[6] % 100), 90)
    color_boost = 1.05 + (digest[7] % 40) / 100.0
    contrast_boost = 1.02 + (digest[8] % 25) / 100.0

    img = ImageEnhance.Color(img).enhance(color_boost)
    img = ImageEnhance.Contrast(img).enhance(contrast_boost)
    img = img.filter(ImageFilter.SMOOTH_MORE)
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    x0 = int(w * (0.08 + (digest[9] % 8) / 100.0))
    y0 = int(h * (0.18 + (digest[10] % 10) / 100.0))
    x1 = int(w * (0.92 - (digest[11] % 8) / 100.0))
    y1 = int(h * (0.85 - (digest[12] % 8) / 100.0))
    draw.rectangle([x0, y0, x1, y1], fill=accent)
    draw.rectangle([x0, y0, x1, y0 + max(8, int(h * 0.06))], fill=band)
    label_color = (255, 255, 255, 200)
    draw.rectangle([w - 120, 12, w - 12, 40], fill=(20, 20, 20, 160))
    draw.text((w - 112, 18), f"Var {digest[0]:02x}{digest[1]:02x}", fill=label_color)
    img.save(dest, quality=92)
    return f"redesigns/{name}"
