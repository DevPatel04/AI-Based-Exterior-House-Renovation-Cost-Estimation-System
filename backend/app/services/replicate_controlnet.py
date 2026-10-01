"""Replicate SDXL ControlNet redesign — free-trial friendly alternative to fal.ai.

Uses the same Canny control map approach as home-improvement / Facades-ControlNet
demos, but runs on Replicate's cloud GPUs (no local GPU / Railway GPU needed).

Get a token: https://replicate.com/account/api-tokens
New accounts usually get free credit to try models.
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
from app.services.image_control import canny_control_png_bytes, data_uri_png
from app.services.storage import ensure_upload_dirs

logger = logging.getLogger(__name__)


def _clean_token(raw: str) -> str:
    token = (raw or "").strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
        token = token[1:-1].strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


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


async def generate_replicate_controlnet_redesign(
    source_path: Path, prompt: str
) -> tuple[str | None, str | None]:
    """
    Call Replicate SDXL ControlNet (Canny).
    Returns (relative_path, error_message). path is set on success.
    """
    settings = get_settings()
    token = _clean_token(settings.replicate_api_token or "")
    if not token or not settings.enable_replicate_controlnet:
        return None, "REPLICATE_API_TOKEN missing or disabled"

    model = (settings.replicate_controlnet_model or "lucataco/sdxl-controlnet").strip()
    try:
        control_png = canny_control_png_bytes(source_path)
        control_uri = data_uri_png(control_png)
        src = Image.open(source_path).convert("RGB")
        src.thumbnail((1024, 1024))
        buf = io.BytesIO()
        src.save(buf, format="PNG")
        source_uri = data_uri_png(buf.getvalue())
    except Exception as exc:
        return None, f"could not build control image: {exc}"

    negative = (
        "blurry, distorted geometry, warped windows, extra floors, people, text, watermark, "
        "cartoon, low quality, different building layout"
    )
    payload = {
        "input": {
            "prompt": prompt,
            "negative_prompt": negative,
            "image": control_uri,
            "condition_scale": float(settings.replicate_controlnet_scale),
            "num_inference_steps": int(settings.replicate_controlnet_steps),
            "guidance_scale": 7.5,
            "num_outputs": 1,
        }
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "wait=60",
    }

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            logger.info("REDESIGN replicate_call start model=%s", model)
            resp = await client.post(
                f"https://api.replicate.com/v1/models/{model}/predictions",
                headers=headers,
                json=payload,
            )
            if resp.status_code >= 400:
                logger.warning(
                    "REDESIGN replicate_call canny_rejected status=%s body=%s — retry original image",
                    resp.status_code,
                    resp.text[:200],
                )
                payload["input"]["image"] = source_uri
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
                logger.error("REDESIGN replicate_call auth_fail %s", err)
                return None, err
            if resp.status_code == 429:
                err = "HTTP 429 rate limit / no credits — check https://replicate.com/account"
                logger.error("REDESIGN replicate_call %s", err)
                return None, err
            if resp.status_code >= 400:
                err = f"HTTP {resp.status_code}: {resp.text[:180]}"
                logger.warning("REDESIGN replicate_call http_error %s", err)
                return None, err

            data = resp.json()
            output = data.get("output")
            status = (data.get("status") or "").lower()
            get_url = (data.get("urls") or {}).get("get")
            pred_id = data.get("id")

            if not output and get_url:
                import asyncio

                logger.info("REDESIGN replicate_call polling id=%s status=%s", pred_id, status)
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
                        return None, f"prediction {status}: {(body.get('error') or '')[:160]}"
                    await asyncio.sleep(2.0)

            if not output:
                return None, "no output from Replicate (timeout or empty)"
            img_url = output[0] if isinstance(output, list) else output
            if not isinstance(img_url, str):
                return None, f"unexpected output type: {type(output).__name__}"
            raw = await _download_image(img_url, client)
            if not raw:
                return None, "could not download result image"

            root = ensure_upload_dirs()
            name = f"{uuid.uuid4().hex}.png"
            dest = root / "redesigns" / name
            try:
                Image.open(io.BytesIO(raw)).convert("RGB").save(dest, format="PNG")
            except Exception:
                dest.write_bytes(raw)
            logger.info("REDESIGN replicate_call ok id=%s path=redesigns/%s", pred_id, name)
            return f"redesigns/{name}", None
    except Exception as exc:
        logger.exception("REDESIGN replicate_call exception")
        return None, str(exc)[:200]
