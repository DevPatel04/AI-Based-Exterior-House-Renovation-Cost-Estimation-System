"""Replicate google/nano-banana-2 redesign — Google image edit from the real house photo.

Uses image_input + prompt so materials change while keeping the facade photoreal.
Docs: https://replicate.com/google/nano-banana-2/api
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


def _clean_token(raw: str) -> str:
    token = (raw or "").strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
        token = token[1:-1].strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


def _data_uri_jpeg(path: Path, max_edge: int = 1536) -> str:
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


async def _download_image(url: str, client: httpx.AsyncClient) -> bytes | None:
    if url.startswith("data:"):
        try:
            _, b64 = url.split(",", 1)
            return base64.b64decode(b64)
        except Exception:
            return None
    resp = await client.get(url, timeout=120.0)
    if resp.status_code >= 400:
        return None
    return resp.content


async def generate_nano_banana_redesign(
    source_path: Path,
    prompt: str,
    hq_mode: bool = False,
) -> tuple[str | None, str | None]:
    """
    Call google/nano-banana-2 with the house photo as image_input.
    Returns (relative_path, error_message).
    """
    settings = get_settings()
    token = _clean_token(settings.replicate_api_token or "")
    if not token or not settings.enable_nano_banana:
        return None, "REPLICATE_API_TOKEN missing or ENABLE_NANO_BANANA=false"

    model = (settings.nano_banana_model or "google/nano-banana-2").strip()
    try:
        image_uri = _data_uri_jpeg(source_path, max_edge=2048 if hq_mode else 1536)
    except Exception as exc:
        return None, f"could not read image: {exc}"

    resolution = "2K" if hq_mode else (settings.nano_banana_resolution or "1K")
    payload = {
        "input": {
            "prompt": prompt,
            "image_input": [image_uri],
            "aspect_ratio": "match_input_image",
            "resolution": resolution,
            "output_format": "jpg",
            "google_search": False,
            "image_search": False,
        }
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "wait=55",
    }

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            logger.info(
                "REDESIGN nano_banana start model=%s resolution=%s hq=%s",
                model,
                resolution,
                hq_mode,
            )
            resp = await client.post(
                f"https://api.replicate.com/v1/models/{model}/predictions",
                headers=headers,
                json=payload,
            )
            if resp.status_code in (401, 403):
                err = (
                    f"HTTP {resp.status_code} invalid REPLICATE_API_TOKEN — "
                    "set a valid token from https://replicate.com/account/api-tokens"
                )
                logger.error("REDESIGN nano_banana auth_fail %s", err)
                return None, err
            if resp.status_code == 429:
                return None, "HTTP 429 rate limit / no credits — check https://replicate.com/account"
            if resp.status_code >= 400:
                err = f"HTTP {resp.status_code}: {resp.text[:220]}"
                logger.warning("REDESIGN nano_banana %s", err)
                return None, err

            data = resp.json()
            output = data.get("output")
            status = (data.get("status") or "").lower()
            get_url = (data.get("urls") or {}).get("get")
            pred_id = data.get("id")

            if not output and get_url:
                import asyncio

                logger.info("REDESIGN nano_banana polling id=%s status=%s", pred_id, status)
                for _ in range(60):
                    st = await client.get(get_url, headers={"Authorization": f"Bearer {token}"})
                    if st.status_code >= 400:
                        return None, f"poll HTTP {st.status_code}"
                    body = st.json()
                    status = (body.get("status") or "").lower()
                    if status == "succeeded":
                        output = body.get("output")
                        break
                    if status in {"failed", "canceled"}:
                        return None, f"prediction {status}: {(body.get('error') or '')[:180]}"
                    await asyncio.sleep(1.5)

            if not output:
                return None, "no output from nano-banana-2"
            # Output is typically a single URI string; sometimes a list
            if isinstance(output, list):
                img_url = next((u for u in output if isinstance(u, str)), None)
            elif isinstance(output, str):
                img_url = output
            else:
                return None, f"unexpected output type: {type(output).__name__}"
            if not img_url:
                return None, "empty output URL from nano-banana-2"

            raw = await _download_image(img_url, client)
            if not raw:
                return None, "could not download nano-banana-2 result"

            root = ensure_upload_dirs()
            name = f"{uuid.uuid4().hex}.jpg"
            dest = root / "redesigns" / name
            try:
                Image.open(io.BytesIO(raw)).convert("RGB").save(dest, format="JPEG", quality=93)
            except Exception:
                dest.write_bytes(raw)
            logger.info("REDESIGN nano_banana ok id=%s path=redesigns/%s", pred_id, name)
            return f"redesigns/{name}", None
    except Exception as exc:
        logger.exception("REDESIGN nano_banana exception")
        return None, str(exc)[:200]
