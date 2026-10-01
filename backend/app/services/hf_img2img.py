"""Hugging Face image-to-image redesign (optional free-credit fallback).

Uses the same HF_TOKEN as SegFormer. Free accounts get a small monthly Inference
Providers credit — fine as a backup when Cloudflare/Replicate are unavailable.
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


async def generate_hf_img2img_redesign(
    source_path: Path,
    prompt: str,
    hq_mode: bool = False,
) -> tuple[str | None, str | None]:
    settings = get_settings()
    token = (settings.hf_token or "").strip()
    if not token:
        return None, "HF_TOKEN missing"

    model = (settings.hf_img2img_model or "stabilityai/stable-diffusion-xl-base-1.0").strip()
    try:
        img = Image.open(source_path).convert("RGB")
        img.thumbnail((768, 768))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        body = buf.getvalue()
        b64 = base64.b64encode(body).decode("ascii")
    except Exception as exc:
        return None, f"could not read image: {exc}"

    url = f"https://router.huggingface.co/hf-inference/models/{model}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "image/png",
        "X-Wait-For-Model": "true",
    }
    payload = {
        "inputs": b64,
        "parameters": {
            "prompt": prompt,
            "strength": 0.58 if hq_mode else 0.5,
            "guidance_scale": 7.5,
            "num_inference_steps": 20 if hq_mode else 15,
            "negative_prompt": (
                "blurry, distorted windows, warped roof, people, text, watermark, cartoon"
            ),
        },
    }
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            logger.info("REDESIGN hf_img2img start model=%s", model)
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                # Some providers want multipart / different schema — try raw image + prompt header style
                logger.warning(
                    "REDESIGN hf_img2img json_fail status=%s body=%s",
                    resp.status_code,
                    resp.text[:180],
                )
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "image/jpeg",
                        "Accept": "image/png",
                        "X-Wait-For-Model": "true",
                    },
                    content=body,
                    params={"prompt": prompt[:400]},
                )
            if resp.status_code >= 400:
                return None, f"HTTP {resp.status_code}: {resp.text[:160]}"

            ctype = resp.headers.get("content-type", "")
            root = ensure_upload_dirs()
            name = f"{uuid.uuid4().hex}.png"
            dest = root / "redesigns" / name
            if "image" in ctype:
                dest.write_bytes(resp.content)
            else:
                try:
                    data = resp.json()
                except Exception:
                    return None, "non-image response"
                # Unexpected JSON — not usable
                return None, f"unexpected JSON: {str(data)[:120]}"
            logger.info("REDESIGN hf_img2img ok path=redesigns/%s", name)
            return f"redesigns/{name}", None
    except Exception as exc:
        logger.warning("REDESIGN hf_img2img exception: %s", exc)
        return None, str(exc)[:180]
