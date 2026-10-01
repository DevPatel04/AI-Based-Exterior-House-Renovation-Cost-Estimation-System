"""Replicate SDXL img2img redesign — starts from the real house photo.

Uses lucataco/sdxl with `image` + `prompt_strength` so geometry stays closer to
the original than text-only / loose generative models.
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
from app.services.image_control import data_uri_png
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


async def generate_replicate_img2img_redesign(
    source_path: Path,
    prompt: str,
    hq_mode: bool = False,
) -> tuple[str | None, str | None]:
    """
    Img2img from the original exterior photo.
    Lower prompt_strength = more accurate structure; higher = stronger material change.
    """
    settings = get_settings()
    token = _clean_token(settings.replicate_api_token or "")
    if not token or not settings.enable_replicate_img2img:
        return None, "REPLICATE_API_TOKEN missing or ENABLE_REPLICATE_IMG2IMG=false"

    model = (settings.replicate_img2img_model or "lucataco/sdxl").strip()
    try:
        src = Image.open(source_path).convert("RGB")
        # SDXL prefers multiples of 8 near 1024
        src.thumbnail((1024, 1024))
        w, h = src.size
        w8, h8 = max(768, (w // 8) * 8), max(768, (h // 8) * 8)
        if (w8, h8) != (w, h):
            src = src.resize((w8, h8), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        src.save(buf, format="PNG")
        source_uri = data_uri_png(buf.getvalue())
        width, height = src.size
    except Exception as exc:
        return None, f"could not read image: {exc}"

    # Keep structure: 0.35–0.55. HQ slightly stronger material edit.
    strength = float(settings.replicate_img2img_strength or 0.42)
    if hq_mode:
        strength = min(0.58, strength + 0.08)
    steps = int(settings.replicate_img2img_steps or 20)
    if hq_mode:
        steps = min(35, steps + 8)

    negative = (
        "blurry, distorted geometry, warped windows, melted glass, extra floors, "
        "different building layout, invented architecture, people, text, watermark, "
        "cartoon, illustration, CGI, 3d render, anime, oversaturated, plastic look, "
        "low quality, fake textures, morphing walls"
    )
    payload = {
        "input": {
            "prompt": prompt,
            "negative_prompt": negative,
            "image": source_uri,
            "prompt_strength": strength,
            "num_inference_steps": steps,
            "guidance_scale": 6.5,
            "num_outputs": 1,
            "width": width,
            "height": height,
            "scheduler": "K_EULER",
            "refine": "no_refiner",
            "apply_watermark": False,
        }
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "wait=55",
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            logger.info(
                "REDESIGN replicate_img2img start model=%s strength=%s steps=%s size=%sx%s",
                model,
                strength,
                steps,
                width,
                height,
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
                logger.error("REDESIGN replicate_img2img auth_fail %s", err)
                return None, err
            if resp.status_code == 429:
                return None, "HTTP 429 rate limit / no credits — check https://replicate.com/account"
            if resp.status_code >= 400:
                err = f"HTTP {resp.status_code}: {resp.text[:180]}"
                logger.warning("REDESIGN replicate_img2img %s", err)
                return None, err

            data = resp.json()
            output = data.get("output")
            status = (data.get("status") or "").lower()
            get_url = (data.get("urls") or {}).get("get")
            pred_id = data.get("id")

            if not output and get_url:
                import asyncio

                logger.info("REDESIGN replicate_img2img polling id=%s status=%s", pred_id, status)
                for _ in range(40):
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
                    await asyncio.sleep(1.5)

            if not output:
                return None, "no output from Replicate img2img"
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
            logger.info("REDESIGN replicate_img2img ok id=%s path=redesigns/%s", pred_id, name)
            return f"redesigns/{name}", None
    except Exception as exc:
        logger.exception("REDESIGN replicate_img2img exception")
        return None, str(exc)[:200]
