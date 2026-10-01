"""Optional fal.ai ControlNet redesign — no local GPU required.

Uses OpenCV Canny edges of the house photo as the control map so massing /
openings stay closer to the original facade than plain img2img.
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

FAL_QUEUE_BASE = "https://queue.fal.run"
FAL_RUN_BASE = "https://fal.run"


async def _download_image(url: str, client: httpx.AsyncClient) -> bytes | None:
    if url.startswith("data:"):
        # data:image/...;base64,....
        try:
            _, b64 = url.split(",", 1)
            return base64.b64decode(b64)
        except Exception:
            return None
    resp = await client.get(url, timeout=120.0)
    if resp.status_code >= 400:
        return None
    return resp.content


async def generate_fal_controlnet_redesign(source_path: Path, prompt: str) -> str | None:
    """
    Call fal.ai ControlNet (Canny). Returns relative redesign path or None on failure.
    Requires FAL_KEY. No local GPU.
    """
    settings = get_settings()
    key = (settings.fal_key or "").strip()
    if not key:
        return None

    model = (settings.fal_controlnet_model or "fal-ai/fast-sdxl-controlnet-canny").strip()
    try:
        control_png = canny_control_png_bytes(source_path)
    except Exception:
        return None

    control_uri = data_uri_png(control_png)
    negative = (
        "blurry, distorted geometry, warped windows, extra floors, people, text, watermark, "
        "cartoon, low quality, different building layout"
    )
    payload = {
        "prompt": prompt,
        "negative_prompt": negative,
        "control_image_url": control_uri,
        "controlnet_conditioning_scale": float(settings.fal_controlnet_scale),
        "num_inference_steps": int(settings.fal_controlnet_steps),
        "guidance_scale": 7.0,
        "num_images": 1,
        "format": "png",
        "enable_safety_checker": True,
    }
    headers = {
        "Authorization": f"Key {key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            # Prefer queue API (handles long runs); fall back to sync fal.run
            submit = await client.post(
                f"{FAL_QUEUE_BASE}/{model}",
                headers=headers,
                json=payload,
            )
            if submit.status_code >= 400:
                # Try sync endpoint once
                sync = await client.post(
                    f"{FAL_RUN_BASE}/{model}",
                    headers=headers,
                    json=payload,
                )
                if sync.status_code >= 400:
                    return None
                data = sync.json()
            else:
                meta = submit.json()
                status_url = meta.get("status_url")
                response_url = meta.get("response_url")
                request_id = meta.get("request_id")
                if not status_url and request_id:
                    status_url = f"{FAL_QUEUE_BASE}/{model}/requests/{request_id}/status"
                    response_url = f"{FAL_QUEUE_BASE}/{model}/requests/{request_id}"

                data = None
                for _ in range(90):  # ~3 min max
                    st = await client.get(status_url, headers=headers)
                    if st.status_code >= 400:
                        return None
                    body = st.json()
                    status = (body.get("status") or "").upper()
                    if status in {"COMPLETED", "OK"}:
                        res = await client.get(response_url or status_url.replace("/status", ""), headers=headers)
                        if res.status_code >= 400:
                            return None
                        data = res.json()
                        break
                    if status in {"FAILED", "ERROR", "CANCELLED"}:
                        return None
                    import asyncio

                    await asyncio.sleep(2.0)
                if data is None:
                    return None

            images = data.get("images") or []
            if not images:
                return None
            first = images[0]
            img_url = first.get("url") if isinstance(first, dict) else None
            if not img_url:
                return None
            raw = await _download_image(img_url, client)
            if not raw:
                return None

            root = ensure_upload_dirs()
            name = f"{uuid.uuid4().hex}.png"
            dest = root / "redesigns" / name
            # Normalize via Pillow in case of jpeg content-type
            try:
                Image.open(io.BytesIO(raw)).convert("RGB").save(dest, format="PNG")
            except Exception:
                dest.write_bytes(raw)
            return f"redesigns/{name}"
    except Exception:
        return None
