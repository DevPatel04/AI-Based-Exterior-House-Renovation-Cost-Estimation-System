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
    Redesign engines:
      1) Gemini Nano Banana image edit (required / primary)
      2) Cloudflare Lightning only if ENABLE_CLOUDFLARE_REDESIGN=true (backup)
    """
    from app.services.material_regions import RegionMaterialAssignment

    settings = get_settings()
    notes: list[str] = []
    region_assignments: list[RegionMaterialAssignment] = [
        a for a in (assignments or []) if isinstance(a, RegionMaterialAssignment)
    ]
    has_gemini = bool(
        (settings.gemini_api_key or "").strip()
        and getattr(settings, "enable_gemini_redesign", True)
    )
    has_cf = bool(
        settings.enable_cloudflare_redesign
        and (settings.cloudflare_account_id or "").strip()
        and (settings.cloudflare_api_token or "").strip()
    )
    logger.info(
        "REDESIGN begin gemini=%s cf=%s hq=%s regions=%s",
        has_gemini,
        has_cf,
        hq_mode,
        len(region_assignments),
    )

    if region_assignments:
        notes.append(f"materials_in_prompt: {len(region_assignments)} regions")

    if not has_gemini:
        notes.append(
            "gemini: set GEMINI_API_KEY and ENABLE_GEMINI_REDESIGN=true "
            "(paid Nano Banana image models: gemini-2.5-flash-image / gemini-3-pro-image)"
        )
        if not has_cf:
            raise RedesignUnavailableError(notes)

    if has_gemini:
        logger.info("REDESIGN try gemini image hq=%s", hq_mode)
        path, model_used, gem_err = await _gemini_image_edit(source_path, prompt, hq_mode=hq_mode)
        if path:
            path = _resize_ai_to_source(source_path, path)
            notes.append(f"gemini_model={model_used}")
            notes.append("raw_gemini_output")
            logger.info("REDESIGN ok engine=gemini_image model=%s", model_used)
            return path, "gemini_image", notes
        notes.append(f"gemini: {gem_err or 'failed'}")

    if has_cf:
        logger.info("REDESIGN try cloudflare backup hq=%s", hq_mode)
        path, cf_err = await _cloudflare_generate(source_path, prompt, hq_mode=hq_mode)
        if path:
            path = _resize_ai_to_source(source_path, path)
            notes.append("raw_cloudflare_output")
            logger.info("REDESIGN ok engine=cloudflare path=%s", path)
            return path, "cloudflare", notes
        notes.append(f"cloudflare: {cf_err or 'request failed'}")

    logger.error("REDESIGN failed notes=%s", notes)
    raise RedesignUnavailableError(notes)


class RedesignUnavailableError(Exception):
    """Redesign engines failed."""

    def __init__(self, notes: list[str]):
        self.notes = notes
        super().__init__("; ".join(notes) if notes else "No redesign engine available")


def _resize_ai_to_source(source_path: Path, ai_rel: str) -> str:
    """Match After panel size to Before — pixels stay AI-only (no blend)."""
    root = ensure_upload_dirs()
    ai_path = root / ai_rel
    if not ai_path.exists():
        return ai_rel
    try:
        src = Image.open(source_path)
        ai = Image.open(ai_path).convert("RGB")
        if ai.size == src.size:
            return ai_rel
        ai = ai.resize(src.size, Image.Resampling.LANCZOS)
        name = f"{uuid.uuid4().hex}.jpg"
        dest = root / "redesigns" / name
        ai.save(dest, format="JPEG", quality=94, optimize=True)
        return f"redesigns/{name}"
    except Exception as exc:
        logger.warning("REDESIGN resize skipped: %s", exc)
        return ai_rel


def _layout_similarity(source_path: Path, ai_rel: str) -> float:
    """Unused in raw mode — kept for diagnostics / tests."""
    try:
        import numpy as np

        root = ensure_upload_dirs()
        ai_path = root / ai_rel if not Path(ai_rel).is_absolute() else Path(ai_rel)
        if not ai_path.exists():
            return 0.0
        src = Image.open(source_path).convert("L")
        ai = Image.open(ai_path).convert("L")
        size = (96, 96)
        a = np.asarray(src.resize(size, Image.Resampling.BILINEAR), dtype=np.float32)
        b = np.asarray(ai.resize(size, Image.Resampling.BILINEAR), dtype=np.float32)
        mae = float(np.mean(np.abs(a - b))) / 255.0
        return max(0.0, min(1.0, 1.0 - mae))
    except Exception:
        return 0.0


def _blend_ai_onto_photo(source_path: Path, ai_image: Image.Image, ai_weight: float = 0.4) -> Image.Image:
    """Legacy helper (not used for final redesign)."""
    src = Image.open(source_path).convert("RGB")
    ai = ai_image.convert("RGB").resize(src.size, Image.Resampling.LANCZOS)
    if ai.height >= int(src.height * 1.6):
        ai = ai.crop((0, 0, ai.width, ai.height // 2)).resize(src.size, Image.Resampling.LANCZOS)
    w = float(max(0.15, min(0.75, ai_weight)))
    blended = Image.blend(src, ai, w)
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


async def _cloudflare_generate(
    source_path: Path, prompt: str, hq_mode: bool = False
) -> tuple[str | None, str | None]:
    """
    Cloudflare Workers AI — return the real model image bytes.
    Prefer img2img when the model accepts the photo; else txt2img with a strong prompt.
    """
    settings = get_settings()
    configured = (settings.cloudflare_image_model or _DEFAULT_CF_MODEL).strip()
    account = (settings.cloudflare_account_id or "").strip()
    token = (settings.cloudflare_api_token or "").strip()
    if not account or not token:
        return None, "CLOUDFLARE_ACCOUNT_ID or CLOUDFLARE_API_TOKEN empty"

    models: list[str] = []
    for m in (
        configured,
        _DEFAULT_CF_MODEL,
        "@cf/runwayml/stable-diffusion-v1-5-img2img",
        "@cf/stabilityai/stable-diffusion-xl-base-1.0",
    ):
        if m and m not in models:
            models.append(m)

    try:
        img = Image.open(source_path).convert("RGB")
        img.thumbnail((1024, 1024) if hq_mode else (768, 768))
        w, h = img.size
        # SDXL-friendly multiples of 8
        tw = max(512, (w // 8) * 8)
        th = max(512, (h // 8) * 8)
        img = img.resize((tw, th), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        image_b64 = base64.b64encode(buf.getvalue()).decode()

        num_steps = 12 if hq_mode else 8
        strength = 0.55 if hq_mode else 0.45
        photo_prompt = (
            f"{prompt} "
            "Photorealistic exterior house renovation photograph, sharp real materials, "
            "natural daylight, DSLR photo. Same building layout as the reference if provided. "
            "No cartoon, no illustration, no watermark, no logo, no text overlay."
        )
        neg = (
            _CARTOON_NEGATIVE
            + ", alamy, shutterstock, getty, adobe stock, watermark, logo, text, signature"
        )

        # img2img first, then txt2img (Lightning often only supports txt2img)
        payloads: list[tuple[str, dict]] = [
            (
                "img2img",
                {
                    "prompt": photo_prompt,
                    "negative_prompt": neg,
                    "image_b64": image_b64,
                    "strength": strength,
                    "num_steps": num_steps,
                    "guidance": 6.0,
                },
            ),
            (
                "img2img",
                {
                    "prompt": photo_prompt,
                    "negative_prompt": neg,
                    "image": image_b64,
                    "strength": strength,
                    "num_steps": num_steps,
                    "guidance": 6.0,
                },
            ),
            (
                "img2img",
                {
                    "prompt": photo_prompt,
                    "negative_prompt": neg,
                    "init_image": image_b64,
                    "strength": strength,
                    "num_steps": num_steps,
                },
            ),
            (
                "txt2img",
                {
                    "prompt": photo_prompt,
                    "negative_prompt": neg,
                    "num_steps": num_steps,
                    "guidance": 7.0,
                    "width": tw,
                    "height": th,
                },
            ),
        ]

        headers = {"Authorization": f"Bearer {token}"}
        logger.info(
            "REDESIGN cloudflare_call models=%s size=%sx%s steps=%s",
            models,
            tw,
            th,
            num_steps,
        )
        errors: list[str] = []
        async with httpx.AsyncClient(timeout=120.0) as client:
            for try_model in models:
                try_url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{try_model}"
                for mode, payload in payloads:
                    # Skip non-img2img payloads on dedicated img2img model names
                    if "img2img" in try_model.lower() and mode != "img2img":
                        continue
                    label = f"model={try_model} mode={mode}"
                    resp = await client.post(try_url, headers=headers, json=payload)
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
                    raw: bytes | None = None
                    if "image" in content_type:
                        raw = resp.content
                    else:
                        try:
                            data = resp.json()
                        except Exception:
                            errors.append(f"non-json {label}")
                            continue
                        if data.get("success") is False:
                            errors.append(
                                f"API error {label}: {str(data.get('errors') or data)[:140]}"
                            )
                            continue
                        result = data.get("result")
                        if isinstance(result, str):
                            raw = base64.b64decode(result)
                        elif isinstance(result, dict):
                            for key in ("image", "image_b64", "b64_json"):
                                if key in result and isinstance(result[key], str):
                                    val = result[key]
                                    raw = base64.b64decode(
                                        val.split(",", 1)[-1] if "," in val else val
                                    )
                                    break
                    if raw:
                        dest.write_bytes(raw)
                        logger.info("REDESIGN cloudflare ok %s bytes=%s", label, len(raw))
                        return f"redesigns/{name}", None
                    errors.append(f"no image bytes {label}")
            return None, " | ".join(errors[:4]) if errors else "cloudflare request failed"
    except Exception as exc:
        logger.warning("REDESIGN cloudflare exception: %s", exc)
        return None, str(exc)[:180]


async def _gemini_image_edit(
    source_path: Path, prompt: str, hq_mode: bool = False
) -> tuple[str | None, str | None, str | None]:
    """
    Gemini Nano Banana image-to-image edit via REST (responseModalities IMAGE).
    Returns (rel_path, model_id, error).
    """
    settings = get_settings()
    key = (settings.gemini_api_key or "").strip()
    if not key:
        return None, None, "GEMINI_API_KEY empty"

    # Stable image models first (widely available), then newer Pro/Flash Image
    models: list[str] = []
    primary = (settings.gemini_image_model or "gemini-3-pro-image").strip()
    fallback = (getattr(settings, "gemini_image_fallback_model", None) or "gemini-3.1-flash-image").strip()
    legacy = (getattr(settings, "gemini_image_legacy_model", None) or "gemini-2.5-flash-image").strip()
    # Order: HQ prefers Pro; normal prefers faster Flash Image, always end with stable 2.5
    ordered = (primary, fallback, legacy) if (hq_mode or getattr(settings, "enable_gemini_hq", True)) else (
        fallback,
        legacy,
        primary,
    )
    # Put proven stable Nano Banana early so accounts without Gemini 3 access still work
    for m in (*ordered, "gemini-2.5-flash-image", "gemini-2.5-flash-image-preview"):
        if m and m not in models:
            models.append(m)

    edit_prompt = (
        f"{prompt}\n\n"
        "Edit THIS photograph (image-to-image). Keep the SAME house, camera angle, "
        "window/door positions, and surroundings. Only change facade materials as specified. "
        "Photoreal DSLR photo. No watermark, no logo, no text overlay, no new building."
    )

    # Prepare JPEG bytes once
    try:
        img = Image.open(source_path).convert("RGB")
        img.thumbnail((1280, 1280) if hq_mode else (1024, 1024))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        image_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:
        return None, None, f"could not read source image: {exc}"

    errors: list[str] = []
    async with httpx.AsyncClient(timeout=180.0) as client:
        for model_name in models:
            logger.info("REDESIGN gemini_image try model=%s", model_name)
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model_name}:generateContent?key={key}"
            )
            payloads = [
                {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [
                                {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
                                {"text": edit_prompt},
                            ],
                        }
                    ],
                    "generationConfig": {
                        "responseModalities": ["TEXT", "IMAGE"],
                        "temperature": 0.4,
                    },
                },
                # Some older endpoints accept response_mime / imageConfig variants
                {
                    "contents": [
                        {
                            "parts": [
                                {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
                                {"text": edit_prompt},
                            ]
                        }
                    ],
                    "generationConfig": {
                        "responseModalities": ["IMAGE"],
                    },
                },
            ]
            got_image = False
            for payload in payloads:
                try:
                    resp = await client.post(url, json=payload)
                except Exception as exc:
                    errors.append(f"{model_name}: request {exc}"[:180])
                    continue
                if resp.status_code >= 400:
                    err = f"{model_name}: HTTP {resp.status_code} {resp.text[:160]}"
                    logger.warning("REDESIGN gemini_image %s", err)
                    errors.append(err)
                    # Don't retry alternate payload on hard auth/model errors
                    if resp.status_code in {401, 403, 404}:
                        break
                    continue
                try:
                    data = resp.json()
                except Exception:
                    errors.append(f"{model_name}: non-json response")
                    continue

                raw = _extract_gemini_image_bytes(data)
                if not raw:
                    # Log blocking / text-only replies
                    block = (
                        (data.get("promptFeedback") or {}).get("blockReason")
                        or (data.get("candidates") or [{}])[0].get("finishReason")
                    )
                    errors.append(f"{model_name}: no image bytes ({block or 'empty'})")
                    continue

                root = ensure_upload_dirs()
                name = f"{uuid.uuid4().hex}.png"
                dest = root / "redesigns" / name
                dest.write_bytes(raw)
                logger.info(
                    "REDESIGN gemini_image ok model=%s bytes=%s", model_name, len(raw)
                )
                return f"redesigns/{name}", model_name, None

            if not got_image:
                continue

    return None, None, " | ".join(errors[:4]) if errors else "gemini image edit failed"


def _extract_gemini_image_bytes(data: dict) -> bytes | None:
    """Pull inline image bytes from a Gemini generateContent JSON response."""
    for cand in data.get("candidates") or []:
        content = cand.get("content") or {}
        for part in content.get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if not inline:
                continue
            b64 = inline.get("data")
            if not b64:
                continue
            try:
                return base64.b64decode(b64)
            except Exception:
                continue
    return None


async def _gemini_hq(source_path: Path, prompt: str) -> str | None:
    """Backward-compatible wrapper."""
    path, _model, _err = await _gemini_image_edit(source_path, prompt, hq_mode=True)
    return path


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
