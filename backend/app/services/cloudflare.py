import base64
import hashlib
import io
import logging
import re
import uuid
from pathlib import Path

import httpx
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps

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
    assignments: list | None = None,
) -> tuple[str, str, list[str]]:
    """
    Returns (relative_path, engine_used, failure_notes).

    Applies user-selected materials onto each region polygon first, then AI.
    """
    from app.services.material_regions import (
        RegionMaterialAssignment,
        apply_region_materials,
        mask_ai_to_regions,
    )
    from app.services.storage import absolute_path as abs_upload

    settings = get_settings()
    notes: list[str] = []
    has_replicate = bool((settings.replicate_api_token or "").strip())
    region_assignments: list[RegionMaterialAssignment] = [
        a for a in (assignments or []) if isinstance(a, RegionMaterialAssignment)
    ]
    logger.info(
        "REDESIGN begin hq=%s regions=%s replicate=%s nano=%s",
        hq_mode,
        len(region_assignments),
        has_replicate,
        bool(has_replicate and settings.enable_nano_banana),
    )

    material_guide_rel: str | None = None
    material_guide_path: Path | None = None
    if region_assignments:
        material_guide_rel = apply_region_materials(source_path, region_assignments, opacity=0.85)
        if material_guide_rel:
            material_guide_path = abs_upload(material_guide_rel)
            logger.info("REDESIGN material_guide ready path=%s", material_guide_rel)
            notes.append(f"material_guide: applied {len(region_assignments)} region materials")
        else:
            notes.append("material_guide: failed to paint region materials")

    texture_paths: list[Path] = []
    for a in region_assignments:
        if a.texture_path:
            try:
                tp = abs_upload(a.texture_path)
                if tp.exists() and tp not in texture_paths:
                    texture_paths.append(tp)
            except Exception:
                pass

    def _finalize_ai(path: str, weight: float = 0.72) -> str:
        if region_assignments:
            return mask_ai_to_regions(source_path, path, region_assignments, ai_weight=weight)
        return path

    if has_replicate and settings.enable_nano_banana:
        from app.services.replicate_nano_banana import generate_nano_banana_redesign

        logger.info("REDESIGN try nano_banana")
        path, err = await generate_nano_banana_redesign(
            source_path,
            prompt,
            hq_mode=hq_mode,
            guide_path=material_guide_path,
            texture_paths=texture_paths,
        )
        if path:
            path = _finalize_ai(path, 0.78)
            logger.info("REDESIGN ok engine=nano_banana path=%s", path)
            return path, "nano_banana", notes
        notes.append(f"nano_banana: {err or 'failed'}")
        logger.warning("REDESIGN fail nano_banana err=%s", err)
    else:
        notes.append("nano_banana: skipped (token missing or ENABLE_NANO_BANANA=false)")

    if has_replicate and settings.enable_replicate_img2img:
        from app.services.replicate_img2img import generate_replicate_img2img_redesign

        logger.info("REDESIGN try replicate_img2img")
        img2img_src = material_guide_path if material_guide_path else source_path
        path, err = await generate_replicate_img2img_redesign(img2img_src, prompt, hq_mode=hq_mode)
        if path:
            path = _finalize_ai(path, 0.7)
            logger.info("REDESIGN ok engine=replicate_img2img path=%s", path)
            return path, "replicate_img2img", notes
        notes.append(f"replicate_img2img: {err or 'failed'}")
        logger.warning("REDESIGN fail replicate_img2img err=%s", err)
    else:
        notes.append("replicate_img2img: skipped (token missing or ENABLE_REPLICATE_IMG2IMG=false)")

    if has_replicate and settings.enable_replicate_controlnet:
        from app.services.replicate_controlnet import generate_replicate_controlnet_redesign

        logger.info("REDESIGN try replicate_controlnet")
        path, err = await generate_replicate_controlnet_redesign(source_path, prompt)
        if path:
            path = _blend_ai_file_onto_photo(source_path, path, ai_weight=0.55 if hq_mode else 0.45)
            path = _finalize_ai(path, 0.65)
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
            path = _blend_ai_file_onto_photo(source_path, path, ai_weight=0.5)
            path = _finalize_ai(path, 0.65)
            logger.info("REDESIGN ok engine=fal_controlnet path=%s", path)
            return path, "fal_controlnet", notes
        notes.append("fal_controlnet: request failed (403/credits)")
        logger.warning("REDESIGN fail fal_controlnet")
    else:
        notes.append("fal_controlnet: skipped (FAL_KEY missing or disabled)")

    # Guaranteed: selected materials on each region polygon
    if material_guide_rel:
        logger.info("REDESIGN ok engine=region_materials path=%s", material_guide_rel)
        return material_guide_rel, "region_materials", notes

    logger.info("REDESIGN try photo_edit")
    path = _photoreal_photo_edit(source_path, prompt)
    if path:
        logger.info("REDESIGN ok engine=photo_edit path=%s", path)
        return path, "photo_edit", notes

    if (
        settings.enable_cloudflare_redesign
        and settings.cloudflare_account_id
        and settings.cloudflare_api_token
    ):
        logger.info("REDESIGN try cloudflare hq=%s", hq_mode)
        path, cf_err = await _cloudflare_img2img(source_path, prompt, hq_mode=hq_mode)
        if path:
            path = _blend_ai_file_onto_photo(source_path, path, ai_weight=0.35)
            path = _finalize_ai(path, 0.5)
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
            path = _finalize_ai(path, 0.55)
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
            path = _finalize_ai(path, 0.7)
            logger.info("REDESIGN ok engine=gemini_hq path=%s", path)
            return path, "gemini_hq", notes
        notes.append("gemini_hq: no image in response")
        logger.warning("REDESIGN fail gemini_hq")

    if settings.allow_local_redesign_fallback:
        path = (
            material_guide_rel
            or _photoreal_photo_edit(source_path, prompt)
            or _local_fallback_redesign(source_path, prompt)
        )
        engine = "region_materials" if path == material_guide_rel else "photo_edit"
        logger.warning("REDESIGN local_fallback path=%s notes=%s", path, notes)
        return path, engine, notes

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
    """Return (r,g,b, strength) guessed from material wording — strength high enough to see."""
    text = (prompt or "").lower()
    palette: list[tuple[tuple[str, ...], tuple[int, int, int], float]] = [
        (("black granite", "charcoal", "anthracite", "matte black", "black metal"), (28, 28, 30), 0.78),
        (("black",), (36, 36, 38), 0.72),
        (("white marble", "carrara", "white stone"), (245, 242, 236), 0.75),
        (("white", "ivory", "cream"), (248, 244, 236), 0.7),
        (("grey", "gray", "concrete", "cement"), (168, 166, 162), 0.68),
        (("brick", "terracotta", "clay"), (178, 88, 64), 0.72),
        (("wood", "teak", "oak", "timber", "cedar"), (158, 112, 68), 0.68),
        (("marble", "stone", "travertine", "granite"), (218, 212, 204), 0.7),
        (("blue",), (100, 132, 168), 0.68),
        (("green",), (88, 128, 96), 0.68),
        (("beige", "sand", "stucco", "render", "plaster"), (222, 200, 168), 0.7),
        (("metal", "steel", "aluminium", "aluminum", "zinc", "cladding"), (176, 182, 188), 0.7),
        (("paint", "acrylic", "emulsion"), (230, 226, 218), 0.65),
    ]
    for keys, rgb, strength in palette:
        if any(k in text for k in keys):
            return (*rgb, strength)
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # High-contrast but still believable facade color so Design A/B differ clearly
    return (90 + digest[0] % 120, 90 + digest[1] % 100, 90 + digest[2] % 90, 0.65)


def _photoreal_photo_edit(source_path: Path, prompt: str) -> str | None:
    """
    Keep the exact real photograph; apply an OBVIOUS material recolor on the facade
    so before/after is easy to spot (fallback when AI engines fail).
    """
    try:
        img = Image.open(source_path).convert("RGB")
        w, h = img.size
        r, g, b, strength = _material_tint_from_prompt(prompt)
        overlay = Image.new("RGB", img.size, (r, g, b))

        gray = ImageOps.grayscale(img)
        # Stronger facade mask — midtones = walls; protect deep shadow + bright sky
        mask = gray.point(lambda p: int(255 * min(0.95, strength + 0.1)) if 35 < p < 225 else 0)
        # Prefer central building band (crop out some edge sky/ground)
        band = Image.new("L", img.size, 0)
        draw = ImageDraw.Draw(band)
        draw.rectangle(
            [int(w * 0.06), int(h * 0.08), int(w * 0.94), int(h * 0.92)],
            fill=255,
        )
        band = band.filter(ImageFilter.GaussianBlur(max(4, w // 80)))
        mask = ImageChops.multiply(mask, band)
        mask = mask.filter(ImageFilter.GaussianBlur(radius=max(3, w // 160)))

        # Heavy blend so renovation is unmistakable
        recolored = Image.blend(img, overlay, 0.72)
        tinted = Image.composite(recolored, img, mask)

        # Cleaner, brighter renovated look
        tinted = ImageEnhance.Brightness(tinted).enhance(1.08)
        tinted = ImageEnhance.Contrast(tinted).enhance(1.12)
        tinted = ImageEnhance.Color(tinted).enhance(1.1)
        tinted = ImageEnhance.Sharpness(tinted).enhance(1.2)

        # Roof darkening when asked
        if re.search(r"\broof\b", prompt or "", re.I) and re.search(
            r"\b(black|charcoal|dark|metal|zinc|tile)\b", prompt or "", re.I
        ):
            roof = ImageEnhance.Brightness(tinted).enhance(0.72)
            roof = ImageEnhance.Color(roof).enhance(0.85)
            roof_mask = Image.new("L", img.size, 0)
            ImageDraw.Draw(roof_mask).rectangle([0, 0, w, int(h * 0.32)], fill=160)
            roof_mask = roof_mask.filter(ImageFilter.GaussianBlur(14))
            tinted = Image.composite(roof, tinted, roof_mask)

        # Window/trim accent (lighter frames) so openings look refreshed
        if re.search(r"\b(window|door|trim|frame)\b", prompt or "", re.I):
            frames = ImageEnhance.Brightness(tinted).enhance(1.18)
            frame_mask = gray.point(lambda p: 90 if 60 < p < 190 else 0)
            frame_mask = frame_mask.filter(ImageFilter.FIND_EDGES)
            frame_mask = frame_mask.point(lambda p: 140 if p > 20 else 0)
            frame_mask = frame_mask.filter(ImageFilter.GaussianBlur(2))
            tinted = Image.composite(frames, tinted, frame_mask)

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
