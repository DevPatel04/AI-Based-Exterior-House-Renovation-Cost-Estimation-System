import base64
import hashlib
import io
import logging
import re
import uuid
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from app.core.config import get_settings
from app.services.storage import ensure_upload_dirs

logger = logging.getLogger(__name__)

# SDXL Lightning works on most free Workers AI accounts.
# Runway SD1.5 img2img often returns 403 "account is not allowed".
_DEFAULT_CF_MODEL = "@cf/bytedance/stable-diffusion-xl-lightning"

_CARTOON_NEGATIVE = (
    "cartoon, anime, illustration, painting, concept art, sketch, comic, "
    "CGI, 3d render, unreal engine, plastic look, oversaturated, "
    "blurry, distorted windows, warped roof, melted glass, extra floors, "
    "different building, invented architecture, people, text, watermark, low quality"
)


async def generate_redesign(
    source_path: Path,
    prompt: str,
    hq_mode: bool = False,
) -> tuple[str, str, list[str]]:
    """
    Returns (relative_path, engine_used, failure_notes).

    Quality-first order (photorealistic, accurate facade):
      1) Replicate google/nano-banana-2 (Google image edit from photo)
      2) Replicate SDXL img2img
      3) Replicate SDXL ControlNet
      4) fal.ai ControlNet
      5) Photoreal photo edit (always keeps real geometry)
      6) Cloudflare Workers AI only if ENABLE_CLOUDFLARE_REDESIGN=true
      7) Hugging Face / Gemini HQ (optional)
      8) Local fallback if ALLOW_LOCAL_REDESIGN_FALLBACK=true
    """
    settings = get_settings()
    notes: list[str] = []
    has_replicate = bool((settings.replicate_api_token or "").strip())
    logger.info(
        "REDESIGN begin hq=%s replicate=%s nano=%s img2img=%s controlnet=%s fal=%s cloudflare=%s hf=%s local_ok=%s",
        hq_mode,
        has_replicate,
        bool(has_replicate and settings.enable_nano_banana),
        bool(has_replicate and settings.enable_replicate_img2img),
        bool(has_replicate and settings.enable_replicate_controlnet),
        bool((settings.fal_key or "").strip() and settings.enable_fal_controlnet),
        bool(
            settings.enable_cloudflare_redesign
            and settings.cloudflare_account_id
            and settings.cloudflare_api_token
        ),
        bool((settings.hf_token or "").strip() and settings.enable_hf_img2img),
        bool(settings.allow_local_redesign_fallback),
    )

    # 1) Google Nano Banana 2 — best photoreal edit from the house photo
    if has_replicate and settings.enable_nano_banana:
        from app.services.replicate_nano_banana import generate_nano_banana_redesign

        logger.info("REDESIGN try nano_banana")
        path, err = await generate_nano_banana_redesign(source_path, prompt, hq_mode=hq_mode)
        if path:
            logger.info("REDESIGN ok engine=nano_banana path=%s", path)
            return path, "nano_banana", notes
        notes.append(f"nano_banana: {err or 'failed'}")
        logger.warning("REDESIGN fail nano_banana err=%s", err)
    else:
        notes.append("nano_banana: skipped (token missing or ENABLE_NANO_BANANA=false)")

    # 2) Replicate SDXL img2img — backup from the real photo
    if has_replicate and settings.enable_replicate_img2img:
        from app.services.replicate_img2img import generate_replicate_img2img_redesign

        logger.info("REDESIGN try replicate_img2img")
        path, err = await generate_replicate_img2img_redesign(source_path, prompt, hq_mode=hq_mode)
        if path:
            logger.info("REDESIGN ok engine=replicate_img2img path=%s", path)
            return path, "replicate_img2img", notes
        notes.append(f"replicate_img2img: {err or 'failed'}")
        logger.warning("REDESIGN fail replicate_img2img err=%s", err)
    else:
        notes.append("replicate_img2img: skipped (token missing or ENABLE_REPLICATE_IMG2IMG=false)")

    # 3) Replicate ControlNet — structure lock backup
    if has_replicate and settings.enable_replicate_controlnet:
        from app.services.replicate_controlnet import generate_replicate_controlnet_redesign

        logger.info("REDESIGN try replicate_controlnet")
        path, err = await generate_replicate_controlnet_redesign(source_path, prompt)
        if path:
            # Soft-blend keeps photo realism if ControlNet drifts toward illustration
            path = _blend_ai_file_onto_photo(source_path, path, ai_weight=0.55 if hq_mode else 0.45)
            logger.info("REDESIGN ok engine=replicate_controlnet path=%s", path)
            return path, "replicate_controlnet", notes
        notes.append(f"replicate_controlnet: {err or 'failed'}")
        logger.warning("REDESIGN fail replicate_controlnet err=%s", err)
    else:
        notes.append("replicate_controlnet: skipped (REPLICATE_API_TOKEN missing or disabled)")

    # 4) fal ControlNet
    if settings.enable_fal_controlnet and (settings.fal_key or "").strip():
        from app.services.fal_controlnet import generate_fal_controlnet_redesign

        logger.info("REDESIGN try fal_controlnet")
        path = await generate_fal_controlnet_redesign(source_path, prompt)
        if path:
            path = _blend_ai_file_onto_photo(source_path, path, ai_weight=0.5)
            logger.info("REDESIGN ok engine=fal_controlnet path=%s", path)
            return path, "fal_controlnet", notes
        notes.append("fal_controlnet: request failed (403/credits)")
        logger.warning("REDESIGN fail fal_controlnet")
    else:
        notes.append("fal_controlnet: skipped (FAL_KEY missing or disabled)")

    # 5) Photoreal photo edit — keeps the real house photo, applies material color/finish hints
    logger.info("REDESIGN try photo_edit")
    path = _photoreal_photo_edit(source_path, prompt)
    if path:
        logger.info("REDESIGN ok engine=photo_edit path=%s", path)
        return path, "photo_edit", notes

    # 6) Cloudflare — optional; always blended onto the real photo (txt2img alone looks cartoon)
    if (
        settings.enable_cloudflare_redesign
        and settings.cloudflare_account_id
        and settings.cloudflare_api_token
    ):
        logger.info("REDESIGN try cloudflare hq=%s", hq_mode)
        path, cf_err = await _cloudflare_img2img(source_path, prompt, hq_mode=hq_mode)
        if path:
            path = _blend_ai_file_onto_photo(source_path, path, ai_weight=0.35)
            logger.info("REDESIGN ok engine=cloudflare path=%s", path)
            return path, "cloudflare", notes
        notes.append(f"cloudflare: {cf_err or 'request failed'}")
        logger.warning("REDESIGN fail cloudflare err=%s", cf_err)
    else:
        notes.append(
            "cloudflare: skipped (ENABLE_CLOUDFLARE_REDESIGN=false — lightning txt2img looks cartoonish)"
        )

    if (settings.hf_token or "").strip() and settings.enable_hf_img2img:
        from app.services.hf_img2img import generate_hf_img2img_redesign

        logger.info("REDESIGN try hf_img2img")
        path, err = await generate_hf_img2img_redesign(source_path, prompt, hq_mode=hq_mode)
        if path:
            path = _blend_ai_file_onto_photo(source_path, path, ai_weight=0.45)
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
        path = _photoreal_photo_edit(source_path, prompt) or _local_fallback_redesign(source_path, prompt)
        logger.warning("REDESIGN local_fallback path=%s notes=%s", path, notes)
        return path, "photo_edit", notes

    logger.error("REDESIGN unavailable notes=%s", notes)
    raise RedesignUnavailableError(notes)


class RedesignUnavailableError(Exception):
    """All AI redesign engines failed and local fallback is disabled."""

    def __init__(self, notes: list[str]):
        self.notes = notes
        super().__init__("; ".join(notes) if notes else "No redesign engine available")


def _blend_ai_onto_photo(source_path: Path, ai_image: Image.Image, ai_weight: float = 0.4) -> Image.Image:
    """Keep real-photo geometry; mix in AI material changes lightly."""
    src = Image.open(source_path).convert("RGB")
    ai = ai_image.convert("RGB").resize(src.size, Image.Resampling.LANCZOS)
    # If AI returned a stacked/grid collage, take the top half (common CF quirk)
    if ai.height >= int(src.height * 1.6):
        ai = ai.crop((0, 0, ai.width, ai.height // 2)).resize(src.size, Image.Resampling.LANCZOS)
    w = float(max(0.15, min(0.75, ai_weight)))
    blended = Image.blend(src, ai, w)
    # Preserve sharp edges from the original photo
    edges = src.filter(ImageFilter.FIND_EDGES).convert("L")
    edges = ImageOps.autocontrast(edges).point(lambda p: 255 if p > 28 else 0)
    return Image.composite(src, blended, edges)


def _blend_ai_file_onto_photo(source_path: Path, ai_rel: str, ai_weight: float = 0.4) -> str:
    root = ensure_upload_dirs()
    ai_path = root / ai_rel
    if not ai_path.exists():
        return ai_rel
    try:
        ai_img = Image.open(ai_path)
        out = _blend_ai_onto_photo(source_path, ai_img, ai_weight=ai_weight)
        name = f"{uuid.uuid4().hex}.jpg"
        dest = root / "redesigns" / name
        out.save(dest, format="JPEG", quality=92, optimize=True)
        return f"redesigns/{name}"
    except Exception as exc:
        logger.warning("REDESIGN blend failed: %s", exc)
        return ai_rel


def _material_tint_from_prompt(prompt: str) -> tuple[int, int, int, float]:
    """Return (r,g,b, strength) guessed from material wording."""
    text = (prompt or "").lower()
    # (rgb, strength) — strength = how hard to push wall midtones
    palette: list[tuple[tuple[str, ...], tuple[int, int, int], float]] = [
        (("black granite", "charcoal", "anthracite", "matte black", "black metal"), (32, 32, 34), 0.55),
        (("black",), (40, 40, 42), 0.5),
        (("white marble", "carrara", "white stone"), (236, 232, 226), 0.5),
        (("white", "ivory", "cream"), (242, 238, 230), 0.45),
        (("grey", "gray", "concrete", "cement"), (150, 148, 144), 0.45),
        (("brick", "terracotta", "clay"), (168, 84, 62), 0.5),
        (("wood", "teak", "oak", "timber", "cedar"), (150, 110, 70), 0.4),
        (("marble", "stone", "travertine"), (210, 205, 198), 0.4),
        (("blue",), (110, 140, 170), 0.4),
        (("green",), (90, 120, 95), 0.4),
        (("beige", "sand", "stucco"), (210, 190, 160), 0.4),
        (("metal", "steel", "aluminium", "aluminum", "zinc"), (170, 175, 180), 0.4),
    ]
    for keys, rgb, strength in palette:
        if any(k in text for k in keys):
            return (*rgb, strength)
    # Stable hash tint so Design A/B differ without looking random neon
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return (140 + digest[0] % 80, 130 + digest[1] % 70, 120 + digest[2] % 60, 0.35)


def _photoreal_photo_edit(source_path: Path, prompt: str) -> str | None:
    """
    Keep the exact real photograph; gently recolor facade midtones toward chosen materials.
    Always looks like a real photo (never invents a new cartoon house).
    """
    try:
        img = Image.open(source_path).convert("RGB")
        r, g, b, strength = _material_tint_from_prompt(prompt)
        overlay = Image.new("RGB", img.size, (r, g, b))

        # Mask: mid-luminance = likely walls/siding; protect sky (bright) and shadows (dark)
        gray = ImageOps.grayscale(img)
        mask = gray.point(
            lambda p: int(255 * strength) if 45 < p < 210 else 0
        )
        # Soften mask so it doesn't look pasted
        mask = mask.filter(ImageFilter.GaussianBlur(radius=max(2, img.width // 200)))

        tinted = Image.composite(Image.blend(img, overlay, 0.55), img, mask)
        # Roof often mentioned — slightly darken upper band if "roof"/"black" in prompt
        if re.search(r"\broof\b", prompt or "", re.I) and re.search(
            r"\b(black|charcoal|dark|metal|zinc)\b", prompt or "", re.I
        ):
            roof = ImageEnhance.Brightness(tinted).enhance(0.82)
            roof_mask = Image.new("L", img.size, 0)
            draw = ImageDraw.Draw(roof_mask)
            draw.rectangle([0, 0, img.width, int(img.height * 0.28)], fill=110)
            roof_mask = roof_mask.filter(ImageFilter.GaussianBlur(12))
            tinted = Image.composite(roof, tinted, roof_mask)

        tinted = ImageEnhance.Contrast(tinted).enhance(1.04)
        tinted = ImageEnhance.Sharpness(tinted).enhance(1.12)

        root = ensure_upload_dirs()
        name = f"{uuid.uuid4().hex}.jpg"
        dest = root / "redesigns" / name
        tinted.save(dest, format="JPEG", quality=93, optimize=True)
        return f"redesigns/{name}"
    except Exception as exc:
        logger.warning("REDESIGN photo_edit failed: %s", exc)
        return None


async def _cloudflare_img2img(
    source_path: Path, prompt: str, hq_mode: bool = False
) -> tuple[str | None, str | None]:
    """Cloudflare Workers AI — prefer image-conditioned calls; still cartoon-prone."""
    settings = get_settings()
    configured = (settings.cloudflare_image_model or _DEFAULT_CF_MODEL).strip()
    account = (settings.cloudflare_account_id or "").strip()
    token = (settings.cloudflare_api_token or "").strip()
    if not account or not token:
        return None, "CLOUDFLARE_ACCOUNT_ID or CLOUDFLARE_API_TOKEN empty"

    models: list[str] = []
    for m in (configured,):
        if not m or "runwayml" in m.lower():
            continue
        if m not in models:
            models.append(m)
    if not models:
        models = [_DEFAULT_CF_MODEL]

    try:
        img = Image.open(source_path).convert("RGB")
        img.thumbnail((768, 768))
        w, h = img.size
        img = img.resize((max(512, (w // 8) * 8), max(512, (h // 8) * 8)), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        image_b64 = base64.b64encode(buf.getvalue()).decode()

        num_steps = 8 if hq_mode else 6
        strength = 0.38 if hq_mode else 0.32
        photo_prompt = (
            f"{prompt} Photorealistic photograph of the same house, real materials, natural daylight."
        )

        # Prefer img2img; txt2img last (cartoonish)
        payloads = [
            {
                "prompt": photo_prompt,
                "negative_prompt": _CARTOON_NEGATIVE,
                "image_b64": image_b64,
                "strength": strength,
                "num_steps": num_steps,
                "guidance": 6.0,
            },
            {
                "prompt": photo_prompt,
                "negative_prompt": _CARTOON_NEGATIVE,
                "num_steps": num_steps,
                "guidance": 6.0,
                "width": img.size[0],
                "height": img.size[1],
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
                    mode = "img2img" if "image_b64" in payload else "txt2img"
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
                    errors.append(f"no image bytes {label}")
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
    """Last-resort: mild grade of the real photo (never invent architecture)."""
    path = _photoreal_photo_edit(source_path, prompt)
    if path:
        return path
    root = ensure_upload_dirs()
    name = f"{uuid.uuid4().hex}.jpg"
    dest = root / "redesigns" / name
    img = Image.open(source_path).convert("RGB")
    img = ImageEnhance.Contrast(img).enhance(1.06)
    img = ImageEnhance.Color(img).enhance(1.04)
    img.save(dest, quality=92)
    return f"redesigns/{name}"
