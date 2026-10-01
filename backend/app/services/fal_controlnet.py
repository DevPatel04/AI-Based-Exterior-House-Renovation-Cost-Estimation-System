"""Optional fal.ai ControlNet redesign — no local GPU required.

Uses OpenCV Canny edges of the house photo as the control map so massing /
openings stay closer to the original facade than plain img2img.
"""

from __future__ import annotations

import base64
import io
import uuid
from pathlib import Path

import cv2
import httpx
import numpy as np
from PIL import Image

from app.core.config import get_settings
from app.services.storage import ensure_upload_dirs

FAL_QUEUE_BASE = "https://queue.fal.run"
FAL_RUN_BASE = "https://fal.run"


def _canny_control_png_bytes(source_path: Path, max_side: int = 1024) -> bytes:
    """Build a Canny edge map from the house photo for ControlNet."""
    bgr = cv2.imread(str(source_path))
    if bgr is None:
        # Pillow fallback if OpenCV cannot decode (e.g. some WebP)
        rgb = Image.open(source_path).convert("RGB")
        bgr = cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)

    h, w = bgr.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        bgr = cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 80, 180)
    # Soften slightly so ControlNet is not overly rigid
    edges = cv2.dilate(edges, np.ones((2, 2), np.uint8), iterations=1)
    edges_rgb = cv2.cvtColor(edges, cv2.COLOR_GRAY2RGB)
    ok, buf = cv2.imencode(".png", edges_rgb)
    if not ok:
        raise RuntimeError("Failed to encode Canny control image")
    return buf.tobytes()


def _data_uri_png(png_bytes: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")


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
        control_png = _canny_control_png_bytes(source_path)
    except Exception:
        return None

    control_uri = _data_uri_png(control_png)
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
