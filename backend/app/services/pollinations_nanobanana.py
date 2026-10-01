"""Pollinations Nano Banana — free image edit with a reference photo.

Uses the Nano Banana family via Pollinations (optional API key; works anonymously
when the edits endpoint allows it). Falls back to a short-lived public image URL
+ GET /image when multipart is blocked.

Docs: https://gen.pollinations.ai/docs
"""

from __future__ import annotations

import io
import logging
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx
from PIL import Image

from app.core.config import get_settings
from app.services.storage import ensure_upload_dirs

logger = logging.getLogger(__name__)

_EDITS_URL = "https://gen.pollinations.ai/v1/images/edits"
_GET_IMAGE_URL = "https://gen.pollinations.ai/image"
_LEGACY_IMAGE_URL = "https://image.pollinations.ai/prompt"


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


async def _upload_temp_public(raw: bytes, client: httpx.AsyncClient) -> str | None:
    """Short-lived public URL so Pollinations GET can use image=… (no Pollinations key)."""
    # catbox.moe — free anonymous file host
    try:
        resp = await client.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": ("house.jpg", raw, "image/jpeg")},
            timeout=60.0,
        )
        url = (resp.text or "").strip()
        if resp.status_code < 400 and url.startswith("http"):
            return url
        logger.warning("REDESIGN pollinations catbox fail status=%s body=%s", resp.status_code, url[:120])
    except Exception as exc:
        logger.warning("REDESIGN pollinations catbox exception: %s", exc)
    return None


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
    ref = guide_path if guide_path and guide_path.exists() else source_path
    try:
        jpeg = _jpeg_bytes(ref, max_edge=1536 if hq_mode else 1280)
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
        # 1) OpenAI-compatible edits (multipart) — best for reference photo
        try:
            logger.info("REDESIGN pollinations try edits model=%s auth=%s", model, bool(token))
            files = {
                "image": ("house.jpg", jpeg, "image/jpeg"),
            }
            data = {
                "prompt": edit_prompt[:1800],
                "model": model,
                "size": f"{width}x{height}",
                "response_format": "b64_json",
            }
            # Also send source photo if guide was used so model sees both
            if guide_path and guide_path.exists() and guide_path != source_path:
                try:
                    files = [
                        ("image", ("house.jpg", _jpeg_bytes(source_path, 1280), "image/jpeg")),
                        ("image", ("materials.jpg", jpeg, "image/jpeg")),
                    ]
                    data["prompt"] = (
                        edit_prompt[:1600]
                        + " Image 1 = original house. Image 2 = materials mapped on regions — match those finishes."
                    )
                except Exception:
                    pass

            resp = await client.post(
                _EDITS_URL,
                headers=_auth_headers(token),
                data=data,
                files=files,
            )
            if resp.status_code < 400:
                ctype = resp.headers.get("content-type", "")
                if "image" in ctype:
                    saved = await _save_image_bytes(resp.content)
                    if saved:
                        logger.info("REDESIGN pollinations ok via=edits_binary path=%s", saved)
                        return saved, None
                try:
                    body = resp.json()
                    b64 = None
                    if isinstance(body, dict):
                        data_list = body.get("data") or []
                        if data_list and isinstance(data_list[0], dict):
                            b64 = data_list[0].get("b64_json")
                            url = data_list[0].get("url")
                            if url and not b64:
                                img_resp = await client.get(url, timeout=120.0)
                                if img_resp.status_code < 400:
                                    saved = await _save_image_bytes(img_resp.content)
                                    if saved:
                                        logger.info("REDESIGN pollinations ok via=edits_url path=%s", saved)
                                        return saved, None
                    if b64:
                        import base64

                        saved = await _save_image_bytes(base64.b64decode(b64))
                        if saved:
                            logger.info("REDESIGN pollinations ok via=edits_b64 path=%s", saved)
                            return saved, None
                except Exception as exc:
                    errors.append(f"edits parse: {exc}")
            else:
                errors.append(f"edits HTTP {resp.status_code}: {resp.text[:160]}")
                logger.warning("REDESIGN pollinations edits fail %s", errors[-1])
        except Exception as exc:
            errors.append(f"edits exception: {exc}")
            logger.warning("REDESIGN pollinations edits exception: %s", exc)

        # 2) Temp public URL + GET /image (works without key on many Pollinations deployments)
        public_url = await _upload_temp_public(jpeg, client)
        if public_url:
            encoded = quote(edit_prompt[:900], safe="")
            for base in (_GET_IMAGE_URL, _LEGACY_IMAGE_URL):
                try:
                    url = (
                        f"{base}/{encoded}"
                        f"?model={quote(model)}"
                        f"&width={width}&height={height}"
                        f"&nologo=true&enhance=false"
                        f"&image={quote(public_url, safe='')}"
                    )
                    if token:
                        url += f"&key={quote(token)}"
                    logger.info("REDESIGN pollinations try GET base=%s", base)
                    resp = await client.get(url, headers=_auth_headers(token), timeout=180.0)
                    if resp.status_code < 400 and "image" in (resp.headers.get("content-type") or ""):
                        saved = await _save_image_bytes(resp.content)
                        if saved:
                            logger.info("REDESIGN pollinations ok via=get path=%s", saved)
                            return saved, None
                    errors.append(f"GET {base} HTTP {resp.status_code}: {resp.text[:120]}")
                except Exception as exc:
                    errors.append(f"GET {base}: {exc}")

    return None, " | ".join(errors[:3]) if errors else "pollinations nanobanana failed"
