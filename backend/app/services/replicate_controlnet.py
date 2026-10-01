"""Replicate SDXL ControlNet redesign — free-trial friendly alternative to fal.ai.

Uses the same Canny control map approach as home-improvement / Facades-ControlNet
demos, but runs on Replicate's cloud GPUs (no local GPU / Railway GPU needed).

Get a token: https://replicate.com/account/api-tokens
New accounts usually get free credit to try models.
"""

from __future__ import annotations

import base64
import io
import uuid
from pathlib import Path

import httpx
from PIL import Image

from app.core.config import get_settings
from app.services.image_control import canny_control_png_bytes, data_uri_png
from app.services.storage import ensure_upload_dirs


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


async def generate_replicate_controlnet_redesign(source_path: Path, prompt: str) -> str | None:
    """
    Call Replicate SDXL ControlNet (Canny). Returns relative redesign path or None.
    Requires REPLICATE_API_TOKEN.
    """
    settings = get_settings()
    token = (settings.replicate_api_token or "").strip()
    if not token or not settings.enable_replicate_controlnet:
        return None

    model = (settings.replicate_controlnet_model or "lucataco/sdxl-controlnet").strip()
    try:
        control_png = canny_control_png_bytes(source_path)
        control_uri = data_uri_png(control_png)
        # Also keep a smaller original for models that canny-internally
        src = Image.open(source_path).convert("RGB")
        src.thumbnail((1024, 1024))
        buf = io.BytesIO()
        src.save(buf, format="PNG")
        source_uri = data_uri_png(buf.getvalue())
    except Exception:
        return None

    negative = (
        "blurry, distorted geometry, warped windows, extra floors, people, text, watermark, "
        "cartoon, low quality, different building layout"
    )
    # lucataco/sdxl-controlnet + similar models expect `image` (often original or canny)
    # and `condition_scale`. We send the Canny map as the conditioning image.
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
        "Prefer": "wait=90",
    }

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"https://api.replicate.com/v1/models/{model}/predictions",
                headers=headers,
                json=payload,
            )
            # Some models reject canny-only; retry once with the original photo
            if resp.status_code >= 400:
                payload["input"]["image"] = source_uri
                resp = await client.post(
                    f"https://api.replicate.com/v1/models/{model}/predictions",
                    headers=headers,
                    json=payload,
                )
            if resp.status_code >= 400:
                return None

            data = resp.json()
            output = data.get("output")
            status = (data.get("status") or "").lower()
            get_url = (data.get("urls") or {}).get("get")

            if not output and get_url:
                import asyncio

                for _ in range(60):
                    st = await client.get(get_url, headers={"Authorization": f"Bearer {token}"})
                    if st.status_code >= 400:
                        return None
                    body = st.json()
                    status = (body.get("status") or "").lower()
                    if status == "succeeded":
                        output = body.get("output")
                        break
                    if status in {"failed", "canceled"}:
                        return None
                    await asyncio.sleep(2.0)

            if not output:
                return None
            img_url = output[0] if isinstance(output, list) else output
            if not isinstance(img_url, str):
                return None
            raw = await _download_image(img_url, client)
            if not raw:
                return None

            root = ensure_upload_dirs()
            name = f"{uuid.uuid4().hex}.png"
            dest = root / "redesigns" / name
            try:
                Image.open(io.BytesIO(raw)).convert("RGB").save(dest, format="PNG")
            except Exception:
                dest.write_bytes(raw)
            return f"redesigns/{name}"
    except Exception:
        return None
