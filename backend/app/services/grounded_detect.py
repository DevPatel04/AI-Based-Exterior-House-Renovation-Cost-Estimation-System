"""Replicate Grounded-SAM structure detection (backup when HF SegFormer fails)."""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

import httpx
import numpy as np
from fastapi.concurrency import run_in_threadpool
from PIL import Image

from app.core.config import get_settings
from app.models import RegionType
from app.services.segformer import StructureDetectError, _mask_to_regions

logger = logging.getLogger(__name__)

_PROMPT_MAP = [
    ("main wall of the house facade", RegionType.main_wall.value, "Main wall"),
    ("window", RegionType.window.value, "Window"),
    ("door entrance", RegionType.gate.value, "Door / gate"),
    ("balcony", RegionType.balcony.value, "Balcony"),
    ("roof edge", RegionType.roof_edge.value, "Roof edge"),
    ("railing", RegionType.railing.value, "Railing"),
    ("pillar column", RegionType.pillar.value, "Pillar"),
]


def _detect_grounded_sync(image_path: Path) -> list[dict]:
    settings = get_settings()
    token = (settings.replicate_api_token or "").strip()
    if not token:
        raise StructureDetectError(
            "SegFormer failed and REPLICATE_API_TOKEN is not set for Grounded-SAM backup."
        )

    img = Image.open(image_path).convert("RGB")
    img.thumbnail((768, 768))
    width, height = img.size
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    data_uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    # Combined prompt (Grounded-SAM style)
    prompt = " . ".join(p[0] for p in _PROMPT_MAP)
    model = (settings.replicate_seg_model or "schananas/grounded_sam").strip()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "wait=45",
    }
    payload = {
        "input": {
            "image": data_uri,
            "prompt": prompt,
            "negative_prompt": "tree, person, car, sky, ground only",
            "box_threshold": 0.25,
            "text_threshold": 0.20,
        }
    }

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            f"https://api.replicate.com/v1/models/{model}/predictions",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            # Alternate common grounded-sam schema
            payload["input"] = {
                "image": data_uri,
                "query": prompt,
            }
            resp = client.post(
                f"https://api.replicate.com/v1/models/{model}/predictions",
                headers=headers,
                json=payload,
            )
        if resp.status_code >= 400:
            raise StructureDetectError(f"Replicate segmentation failed: {resp.status_code} {resp.text[:180]}")

        data = resp.json()
        output = data.get("output")
        get_url = (data.get("urls") or {}).get("get")
        if not output and get_url:
            import time

            for _ in range(40):
                time.sleep(1.5)
                st = client.get(get_url, headers={"Authorization": f"Bearer {token}"})
                body = st.json()
                status = (body.get("status") or "").lower()
                if status == "succeeded":
                    output = body.get("output")
                    break
                if status in {"failed", "canceled"}:
                    raise StructureDetectError("Replicate Grounded-SAM prediction failed")

        if not output:
            raise StructureDetectError("Replicate Grounded-SAM returned empty output")

        regions = _parse_grounded_output(output, width, height, client)
        if not regions:
            raise StructureDetectError("Grounded-SAM found no facade parts in this photo")
        return regions


def _parse_grounded_output(output, width: int, height: int, client: httpx.Client) -> list[dict]:
    """Best-effort parse of common Grounded-SAM Replicate outputs."""
    regions: list[dict] = []

    # Case: list of mask URLs or dict with masks / detections
    masks = []
    labels = []
    if isinstance(output, dict):
        masks = output.get("masks") or output.get("mask") or output.get("annotated") or []
        labels = output.get("labels") or output.get("tags") or output.get("phrases") or []
        if isinstance(masks, str):
            masks = [masks]
        # Sometimes a single annotated image only — not useful for polygons
        detections = output.get("detections") or output.get("boxes") or []
        if detections and not masks:
            for det in detections:
                if not isinstance(det, dict):
                    continue
                label = str(det.get("label") or det.get("phrase") or "")
                box = det.get("bbox") or det.get("box") or det.get("xyxy")
                rtype = _label_to_type(label)
                if not rtype or not box or len(box) < 4:
                    continue
                x0, y0, x1, y1 = [float(v) for v in box[:4]]
                # normalize if absolute
                if max(x0, y0, x1, y1) > 1.5:
                    x0, x1 = x0 / width, x1 / width
                    y0, y1 = y0 / height, y1 / height
                points = [
                    {"x": round(x0, 4), "y": round(y0, 4)},
                    {"x": round(x1, 4), "y": round(y0, 4)},
                    {"x": round(x1, 4), "y": round(y1, 4)},
                    {"x": round(x0, 4), "y": round(y1, 4)},
                ]
                regions.append(
                    {
                        "region_type": rtype,
                        "label": label.title() or rtype,
                        "points": points,
                        "confidence": float(det.get("confidence") or det.get("score") or 0.65),
                        "source": "grounded_sam",
                    }
                )
            return regions
    elif isinstance(output, list):
        masks = output

    for i, m in enumerate(masks):
        if not isinstance(m, str):
            continue
        try:
            if m.startswith("data:"):
                raw = base64.b64decode(m.split(",", 1)[-1])
            else:
                r = client.get(m, timeout=60.0)
                if r.status_code >= 400:
                    continue
                raw = r.content
            arr = np.array(Image.open(io.BytesIO(raw)).convert("L").resize((width, height), Image.NEAREST))
        except Exception:
            continue
        label = ""
        if isinstance(labels, list) and i < len(labels):
            label = str(labels[i])
        rtype = _label_to_type(label) or RegionType.main_wall.value
        pretty = label.replace("_", " ").title() if label else "Region"
        regions.extend(_mask_to_regions(arr, rtype, pretty, 0.7))
    return regions


def _label_to_type(label: str) -> str | None:
    key = (label or "").lower()
    if any(w in key for w in ("window",)):
        return RegionType.window.value
    if any(w in key for w in ("door", "gate", "entrance")):
        return RegionType.gate.value
    if "balcony" in key or "porch" in key:
        return RegionType.balcony.value
    if "roof" in key or "awning" in key:
        return RegionType.roof_edge.value
    if "rail" in key or "fence" in key:
        return RegionType.railing.value
    if "pillar" in key or "column" in key:
        return RegionType.pillar.value
    if any(w in key for w in ("wall", "facade", "house", "building")):
        return RegionType.main_wall.value
    return None


async def detect_grounded_regions(image_path: Path) -> list[dict]:
    return await run_in_threadpool(_detect_grounded_sync, image_path)
