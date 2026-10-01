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

# SDXL Lightning works on most free Workers AI accounts.
# Runway SD1.5 img2img often returns 403 "account is not allowed".
_DEFAULT_CF_MODEL = "@cf/bytedance/stable-diffusion-xl-lightning"


async def generate_redesign(
    source_path: Path,
    prompt: str,
    hq_mode: bool = False,
) -> tuple[str, str, list[str]]:
    """
    Returns (relative_path, engine_used, failure_notes).

    Quality-first order (photorealistic facade lock):
      1) Replicate SDXL ControlNet (best — keeps real house structure)
      2) fal.ai ControlNet
      3) Cloudflare Workers AI (fallback — more “AI look”)
      4) Hugging Face image-to-image (optional)
      5) Gemini HQ only if explicitly enabled
      6) Local PIL fallback only if ALLOW_LOCAL_REDESIGN_FALLBACK=true
    """
    settings = get_settings()
    notes: list[str] = []
    logger.info(
        "REDESIGN begin hq=%s replicate=%s fal=%s cloudflare=%s hf=%s gemini_hq=%s local_ok=%s",
        hq_mode,
        bool((settings.replicate_api_token or "").strip() and settings.enable_replicate_controlnet),
        bool((settings.fal_key or "").strip() and settings.enable_fal_controlnet),
        bool(settings.cloudflare_account_id and settings.cloudflare_api_token),
        bool((settings.hf_token or "").strip() and settings.enable_hf_img2img),
        bool(hq_mode and settings.enable_gemini_hq and settings.gemini_api_key),
        bool(settings.allow_local_redesign_fallback),
    )

    # 1) Replicate ControlNet first — photorealistic, structure-preserving
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

    # 2) fal ControlNet
    if settings.enable_fal_controlnet and (settings.fal_key or "").strip():
        from app.services.fal_controlnet import generate_fal_controlnet_redesign

        logger.info("REDESIGN try fal_controlnet")
        path = await generate_fal_controlnet_redesign(source_path, prompt)
        if path:
            logger.info("REDESIGN ok engine=fal_controlnet path=%s", path)
            return path, "fal_controlnet", notes
        notes.append("fal_controlnet: request failed (403/credits)")
        logger.warning("REDESIGN fail fal_controlnet")
    else:
        notes.append("fal_controlnet: skipped (FAL_KEY missing or disabled)")

    # 3) Cloudflare — free fallback (more generative / less faithful)
    if settings.cloudflare_account_id and settings.cloudflare_api_token:
        logger.info("REDESIGN try cloudflare hq=%s", hq_mode)
        path, cf_err = await _cloudflare_img2img(source_path, prompt, hq_mode=hq_mode)
        if path:
            logger.info("REDESIGN ok engine=cloudflare path=%s", path)
            return path, "cloudflare", notes
        notes.append(f"cloudflare: {cf_err or 'request failed'}")
        logger.warning("REDESIGN fail cloudflare err=%s", cf_err)
    else:
        notes.append(
            "cloudflare: skipped — set CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN "
            "(free: https://developers.cloudflare.com/workers-ai/get-started/rest-api/)"
        )

    if (settings.hf_token or "").strip() and settings.enable_hf_img2img:
        from app.services.hf_img2img import generate_hf_img2img_redesign

        logger.info("REDESIGN try hf_img2img")
        path, err = await generate_hf_img2img_redesign(source_path, prompt, hq_mode=hq_mode)
        if path:
            logger.info("REDESIGN ok engine=hf_img2img path=%s", path)
            return path, "hf_img2img", notes
        notes.append(f"hf_img2img: {err or 'failed'}")
        logger.warning("REDESIGN fail hf_img2img err=%s", err)
    else:
        notes.append("hf_img2img: skipped (HF_TOKEN missing or ENABLE_HF_IMG2IMG=false)")

    if hq_mode and settings.enable_gemini_hq and settings.gemini_api_key:
        logger.info("REDESIGN try gemini_hq")
        path = await _gemini_hq(source_path, prompt)
        if path:
            logger.info("REDESIGN ok engine=gemini_hq path=%s", path)
            return path, "gemini_hq", notes
        notes.append("gemini_hq: no image in response")
        logger.warning("REDESIGN fail gemini_hq")

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


async def _cloudflare_img2img(
    source_path: Path, prompt: str, hq_mode: bool = False
) -> tuple[str | None, str | None]:
    """Use Cloudflare models that free accounts can access (not Runway img2img)."""
    settings = get_settings()
    configured = (settings.cloudflare_image_model or _DEFAULT_CF_MODEL).strip()
    account = (settings.cloudflare_account_id or "").strip()
    token = (settings.cloudflare_api_token or "").strip()
    if not account or not token:
        return None, "CLOUDFLARE_ACCOUNT_ID or CLOUDFLARE_API_TOKEN empty"

    models: list[str] = []
    for m in (
        configured,
        "@cf/bytedance/stable-diffusion-xl-lightning",
        "@cf/lykon/dreamshaper-8-lcm",
    ):
        # Skip Runway models — this account gets 403 "not allowed to access"
        if not m or "runwayml" in m.lower():
            continue
        if m not in models:
            models.append(m)
    if not models:
        models = [_DEFAULT_CF_MODEL]

    try:
        import io

        img = Image.open(source_path).convert("RGB")
        img.thumbnail((768, 768))
        w, h = img.size
        img = img.resize((max(512, (w // 8) * 8), max(512, (h // 8) * 8)), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_b64 = base64.b64encode(buf.getvalue()).decode()

        num_steps = 8 if hq_mode else 6
        strength = 0.5 if hq_mode else 0.4
        negative = (
            "blurry, distorted windows, warped roof, extra floors, people, text, "
            "watermark, cartoon, low quality, different building layout"
        )

        # txt2img first (reliable on lightning), then optional image_b64 img2img
        payloads = [
            {
                "prompt": prompt,
                "negative_prompt": negative,
                "num_steps": num_steps,
                "guidance": 7.5,
                "width": img.size[0],
                "height": img.size[1],
            },
            {
                "prompt": prompt,
                "negative_prompt": negative,
                "image_b64": image_b64,
                "strength": strength,
                "num_steps": num_steps,
                "guidance": 7.5,
            },
        ]

        headers = {"Authorization": f"Bearer {token}"}
        logger.info(
            "REDESIGN cloudflare_call models=%s size=%sx%s steps=%s",
            models,
            img.size[0],
            img.size[1],
            num_steps,
        )
        errors: list[str] = []
        async with httpx.AsyncClient(timeout=90.0) as client:
            for try_model in models:
                try_url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{try_model}"
                for i, payload in enumerate(payloads):
                    mode = "txt2img" if i == 0 else "img2img"
                    resp = await client.post(try_url, headers=headers, json=payload)
                    label = f"model={try_model} mode={mode}"
                    if resp.status_code >= 400:
                        err = f"HTTP {resp.status_code} {label}: {resp.text[:140]}"
                        logger.warning("REDESIGN cloudflare %s", err)
                        errors.append(err)
                        if resp.status_code == 403 and "not allowed" in resp.text.lower():
                            break
                        continue

                    content_type = resp.headers.get("content-type", "")
                    root = ensure_upload_dirs()
                    name = f"{uuid.uuid4().hex}.png"
                    dest = root / "redesigns" / name
                    if "image" in content_type:
                        dest.write_bytes(resp.content)
                        logger.info("REDESIGN cloudflare ok %s", label)
                        return f"redesigns/{name}", None
                    try:
                        data = resp.json()
                    except Exception:
                        errors.append(f"non-json {label}")
                        continue
                    if data.get("success") is False:
                        errors.append(f"API error {label}: {str(data.get('errors') or data)[:140]}")
                        continue
                    result = data.get("result")
                    raw: bytes | None = None
                    if isinstance(result, str):
                        raw = base64.b64decode(result)
                    elif isinstance(result, dict):
                        for key in ("image", "image_b64", "b64_json"):
                            if key in result and isinstance(result[key], str):
                                val = result[key]
                                raw = base64.b64decode(val.split(",", 1)[-1] if "," in val else val)
                                break
                    if raw:
                        dest.write_bytes(raw)
                        logger.info("REDESIGN cloudflare ok %s", label)
                        return f"redesigns/{name}", None
                    errors.append(f"unexpected result {label}")
            return None, " | ".join(errors[:3]) if errors else "request failed"
    except Exception as exc:
        logger.warning("REDESIGN cloudflare exception: %s", exc)
        return None, str(exc)[:180]


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
    """Deterministic demo overlay — not a real AI redesign."""
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
