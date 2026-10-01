"""Pollinations Nano Banana — image edit with a reference photo.

`gen.pollinations.ai` now requires an API key (free keys: https://enter.pollinations.ai/keys).
Set POLLINATIONS_API_KEY in the backend env. Without a key, this engine returns a clear error
so Cloudflare / region materials can take over.
"""

from __future__ import annotations

import base64
import io
import logging
import uuid
from pathlib import Path

import httpx
from PIL import Image

from app.core.config import get_settings
from app.services.storage import ensure_upload_dirs

logger = logging.getLogger(__name__)

_EDITS_URL = "https://gen.pollinations.ai/v1/images/edits"
_GET_IMAGE_URL = "https://gen.pollinations.ai/image"


def _jpeg_bytes(path: Path, max_edge: int = 1280) -> bytes:
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90, optimize=True)
    return buf.getvalue()


def _auth_headers(token: str | None) -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "image/*,application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _save_image_bytes(raw: bytes) -> str | None:
    if not raw or len(raw) < 100:
        return None
    root = ensure_upload_dirs()
    name = f"{uuid.uuid4().hex}.jpg"
    dest = root / "redesigns" / name
    try:
        Image.open(io.BytesIO(raw)).convert("RGB").save(dest, format="JPEG", quality=93)
    except Exception:
        if raw[:8] == b"\x89PNG\r\n\x1a\n" or raw[:2] == b"\xff\xd8":
            dest.write_bytes(raw)
        else:
            return None
    return f"redesigns/{name}"


async def generate_pollinations_nanobanana_redesign(
    source_path: Path,
    prompt: str,
    hq_mode: bool = False,
    guide_path: Path | None = None,
) -> tuple[str | None, str | None]:
    """
    Edit the house photo with Pollinations model `nanobanana` (reference image).
    Returns (relative_path, error).
    """
    settings = get_settings()
    if not settings.enable_pollinations_nanobanana:
        return None, "ENABLE_POLLINATIONS_NANOBANANA=false"

    model = (settings.pollinations_nanobanana_model or "nanobanana").strip()
    token = (settings.pollinations_api_key or "").strip() or None
    if not token:
        return (
            None,
            "POLLINATIONS_API_KEY missing — gen.pollinations.ai now requires a free key "
            "from https://enter.pollinations.ai/keys (anonymous edits return 401)",
        )

    ref = guide_path if guide_path and guide_path.exists() else source_path
    try:
        jpeg = _jpeg_bytes(ref, max_edge=1536 if hq_mode else 1280)
        source_jpeg = _jpeg_bytes(source_path, max_edge=1536 if hq_mode else 1280)
    except Exception as exc:
        return None, f"could not read image: {exc}"

    edit_prompt = (
        f"{prompt} "
        "Edit THIS reference house photo only — keep the same building and camera angle. "
        "Apply the renovation materials clearly. Photoreal photograph, not a cartoon."
    )
    width = 1280 if hq_mode else 1024
    height = 1280 if hq_mode else 1024
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
        logger.info("REDESIGN pollinations try edits model=%s", model)
        files: list[tuple[str, tuple]] = [
            ("image", ("house.jpg", source_jpeg, "image/jpeg")),
        ]
        data = {
            "prompt": edit_prompt[:1800],
            "model": model,
            "size": f"{width}x{height}",
            "response_format": "b64_json",
        }
        if guide_path and guide_path.exists() and guide_path != source_path:
            files.append(("image", ("materials.jpg", jpeg, "image/jpeg")))
            data["prompt"] = (
                edit_prompt[:1500]
                + " Image 1 = original house. Image 2 = materials on each region — match those finishes."
            )

        try:
            resp = await client.post(
                _EDITS_URL,
                headers=_auth_headers(token),
                data=data,
                files=files,
            )
        except Exception as exc:
            logger.warning("REDESIGN pollinations edits exception: %s", exc)
            return None, f"edits exception: {exc}"

        if resp.status_code in (401, 403):
            err = (
                f"HTTP {resp.status_code} invalid/expired POLLINATIONS_API_KEY — "
                "get a free key at https://enter.pollinations.ai/keys"
            )
            logger.error("REDESIGN pollinations auth_fail %s", err)
            return None, err
        if resp.status_code >= 400:
            err = f"edits HTTP {resp.status_code}: {resp.text[:180]}"
            logger.warning("REDESIGN pollinations %s", err)
            return None, err

        ctype = resp.headers.get("content-type", "")
        if "image" in ctype:
            saved = await _save_image_bytes(resp.content)
            if saved:
                logger.info("REDESIGN pollinations ok via=edits_binary path=%s", saved)
                return saved, None

        try:
            body = resp.json()
            data_list = (body.get("data") or []) if isinstance(body, dict) else []
            if data_list and isinstance(data_list[0], dict):
                item = data_list[0]
                if item.get("b64_json"):
                    saved = await _save_image_bytes(base64.b64decode(item["b64_json"]))
                    if saved:
                        logger.info("REDESIGN pollinations ok via=edits_b64 path=%s", saved)
                        return saved, None
                url = item.get("url")
                if url:
                    img_resp = await client.get(url, timeout=120.0)
                    if img_resp.status_code < 400:
                        saved = await _save_image_bytes(img_resp.content)
                        if saved:
                            logger.info("REDESIGN pollinations ok via=edits_url path=%s", saved)
                            return saved, None
            errors.append(f"unexpected edits JSON keys={list(body)[:8] if isinstance(body, dict) else type(body)}")
        except Exception as exc:
            errors.append(f"edits parse: {exc}")

    return None, " | ".join(errors[:3]) if errors else "pollinations nanobanana failed"
