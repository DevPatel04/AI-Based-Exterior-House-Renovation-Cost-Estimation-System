"""Describe an uploaded exterior photo for redesign prompt context.

Uses Cloudflare Workers AI vision first (same account as redesign),
then Gemini if configured.
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

import httpx
from PIL import Image

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_DEFAULT_VISION_MODEL = "@cf/llava-hf/llava-1.5-7b-hf"
_ALT_VISION_MODEL = "@cf/meta/llama-3.2-11b-vision-instruct"

_DESCRIBE_PROMPT = (
    "Describe this exterior building photo for an architect redesigning the facade. "
    "In 4-6 short sentences cover: building type and approximate floors, wall/roof "
    "materials and colors, window and door layout, roof shape, surroundings "
    "(street, yard, trees, sky), and camera angle. Be factual and specific. "
    "Do not suggest renovations. Do not invent details you cannot see."
)


def _read_image_b64(image_path: Path, max_edge: int = 1024) -> tuple[str, int, int]:
    img = Image.open(image_path).convert("RGB")
    img.thumbnail((max_edge, max_edge))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode("ascii"), img.size[0], img.size[1]


def _clean_description(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = " ".join(str(text).strip().split())
    if len(cleaned) < 24:
        return None
    # Cap so the image-gen prompt stays within model limits
    if len(cleaned) > 900:
        cleaned = cleaned[:897].rsplit(" ", 1)[0] + "…"
    return cleaned


async def _describe_cloudflare(image_path: Path) -> str | None:
    settings = get_settings()
    account = (settings.cloudflare_account_id or "").strip()
    token = (settings.cloudflare_api_token or "").strip()
    if not account or not token:
        return None

    model = (getattr(settings, "cloudflare_vision_model", None) or _DEFAULT_VISION_MODEL).strip()
    models = [m for m in (model, _DEFAULT_VISION_MODEL, _ALT_VISION_MODEL) if m]
    # de-dupe preserving order
    seen: set[str] = set()
    models = [m for m in models if not (m in seen or seen.add(m))]

    image_b64, _, _ = _read_image_b64(image_path)
    headers = {"Authorization": f"Bearer {token}"}
    # Workers AI vision models accept slightly different schemas
    payloads = [
        {"prompt": _DESCRIBE_PROMPT, "image": image_b64, "max_tokens": 280},
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _DESCRIBE_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                        },
                    ],
                }
            ],
            "max_tokens": 280,
        },
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image_b64},
                        {"type": "text", "text": _DESCRIBE_PROMPT},
                    ],
                }
            ],
            "max_tokens": 280,
        },
    ]

    async with httpx.AsyncClient(timeout=60.0) as client:
        for try_model in models:
            url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{try_model}"
            for payload in payloads:
                try:
                    resp = await client.post(url, headers=headers, json=payload)
                except Exception as exc:
                    logger.warning("DESCRIBE cloudflare request failed: %s", exc)
                    continue
                if resp.status_code >= 400:
                    logger.warning(
                        "DESCRIBE cloudflare HTTP %s model=%s: %s",
                        resp.status_code,
                        try_model,
                        resp.text[:160],
                    )
                    continue
                try:
                    data = resp.json()
                except Exception:
                    continue
                if data.get("success") is False:
                    continue
                result = data.get("result")
                text: str | None = None
                if isinstance(result, str):
                    text = result
                elif isinstance(result, dict):
                    text = (
                        result.get("response")
                        or result.get("description")
                        or result.get("text")
                        or result.get("generated_text")
                    )
                    if not text and isinstance(result.get("message"), dict):
                        text = result["message"].get("content")
                cleaned = _clean_description(text if isinstance(text, str) else None)
                if cleaned:
                    logger.info(
                        "DESCRIBE ok engine=cloudflare model=%s chars=%s",
                        try_model,
                        len(cleaned),
                    )
                    return cleaned
    return None


async def _describe_gemini(image_path: Path) -> str | None:
    settings = get_settings()
    if not (settings.gemini_api_key or "").strip():
        return None
    try:
        from fastapi.concurrency import run_in_threadpool

        def _run() -> str | None:
            import google.generativeai as genai

            genai.configure(api_key=settings.gemini_api_key)
            model = genai.GenerativeModel(settings.gemini_model)
            uploaded = genai.upload_file(str(image_path))
            result = model.generate_content([uploaded, _DESCRIBE_PROMPT])
            return _clean_description(getattr(result, "text", None))

        text = await run_in_threadpool(_run)
        if text:
            logger.info("DESCRIBE ok engine=gemini chars=%s", len(text))
        return text
    except Exception as exc:
        logger.warning("DESCRIBE gemini failed: %s", exc)
        return None


async def describe_uploaded_image(image_path: Path) -> tuple[str | None, str | None]:
    """
    Return (description, engine_name).
    Never raises — redesign can continue without a description.
    """
    if not image_path.exists():
        return None, None
    try:
        desc = await _describe_cloudflare(image_path)
        if desc:
            return desc, "cloudflare_vision"
    except Exception as exc:
        logger.warning("DESCRIBE cloudflare crashed: %s", exc)
    try:
        desc = await _describe_gemini(image_path)
        if desc:
            return desc, "gemini_vision"
    except Exception as exc:
        logger.warning("DESCRIBE gemini crashed: %s", exc)
    logger.warning("DESCRIBE unavailable — redesign will use materials prompt only")
    return None, None


def inject_scene_into_prompt(base_prompt: str, scene: str | None) -> str:
    """Prepend photo description so the image model keeps the same house context."""
    scene = (scene or "").strip()
    if not scene:
        return base_prompt
    return (
        "SOURCE PHOTO CONTEXT (match this exact building, camera, and surroundings):\n"
        f"{scene}\n\n"
        f"{base_prompt}"
    )
