"""High-accuracy Replicate fallbacks when Hugging Face SegFormer is weak/unreachable.

1) schananas/grounded_sam — per-class mask_prompt (windows, doors, walls, …)
2) adirik/grounding-dino — open-vocab boxes for openings if masks are thin

Same polygon pipeline as SegFormer (mask/contour → Konva points).
"""

from __future__ import annotations

import base64
import io
import logging
import time
from pathlib import Path

import httpx
import numpy as np
from fastapi.concurrency import run_in_threadpool
from PIL import Image

from app.core.config import get_settings
from app.models import RegionType
from app.services.segformer import (
    StructureDetectError,
    _format_network_error,
    _mask_to_regions,
    _merge_region_lists,
    _pretty_label,
)

logger = logging.getLogger(__name__)

_CLASS_PROMPTS: list[tuple[str, str]] = [
    ("house facade wall, building wall", RegionType.main_wall.value),
    ("window, window pane, glass window", RegionType.window.value),
    ("door, entrance door, front door", RegionType.gate.value),
    ("balcony, porch", RegionType.balcony.value),
    ("roof edge, roofline, cornice", RegionType.roof_edge.value),
    ("railing, fence rail", RegionType.railing.value),
    ("pillar, column", RegionType.pillar.value),
]

_OPENING_PROMPTS: list[tuple[str, str]] = [
    ("window, window pane, glass window", RegionType.window.value),
    ("door, entrance door, front door", RegionType.gate.value),
    ("balcony, porch", RegionType.balcony.value),
    ("roof edge, roofline", RegionType.roof_edge.value),
]


def _image_data_uri(image_path: Path, max_side: int = 1024) -> tuple[str, int, int]:
    img = Image.open(image_path).convert("RGB")
    img.thumbnail((max_side, max_side))
    w, h = img.size
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    return uri, w, h


def _replicate_predict(
    client: httpx.Client,
    token: str,
    model: str,
    input_payload: dict,
) -> dict | list | None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "wait=60",
    }
    prompt_hint = (
        input_payload.get("mask_prompt")
        or input_payload.get("keywords")
        or input_payload.get("query")
        or ""
    )
    if isinstance(prompt_hint, str) and len(prompt_hint) > 60:
        prompt_hint = prompt_hint[:57] + "..."
    t0 = time.perf_counter()
    logger.info("DETECT replicate_call start model=%s prompt=%r", model, prompt_hint)
    try:
        resp = client.post(
            f"https://api.replicate.com/v1/models/{model}/predictions",
            headers=headers,
            json={"input": input_payload},
        )
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError, OSError) as exc:
        raise StructureDetectError(_format_network_error(exc, "Replicate")) from exc

    if resp.status_code >= 400:
        ms = int((time.perf_counter() - t0) * 1000)
        logger.warning(
            "DETECT replicate_call http_error model=%s ms=%s status=%s body=%s",
            model,
            ms,
            resp.status_code,
            resp.text[:200],
        )
        return None

    data = resp.json()
    output = data.get("output")
    get_url = (data.get("urls") or {}).get("get")
    status = (data.get("status") or "").lower()
    pred_id = data.get("id")

    if not output and get_url and status not in {"succeeded", "failed", "canceled"}:
        logger.info(
            "DETECT replicate_call polling model=%s id=%s status=%s",
            model,
            pred_id,
            status,
        )
        for poll in range(45):
            time.sleep(2)
            try:
                st = client.get(get_url, headers={"Authorization": f"Bearer {token}"})
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError, OSError) as exc:
                raise StructureDetectError(_format_network_error(exc, "Replicate")) from exc
            body = st.json()
            status = (body.get("status") or "").lower()
            if status == "succeeded":
                ms = int((time.perf_counter() - t0) * 1000)
                logger.info(
                    "DETECT replicate_call ok model=%s id=%s ms=%s polls=%s",
                    model,
                    pred_id,
                    ms,
                    poll + 1,
                )
                return body.get("output")
            if status in {"failed", "canceled"}:
                ms = int((time.perf_counter() - t0) * 1000)
                logger.warning(
                    "DETECT replicate_call %s model=%s id=%s ms=%s err=%s",
                    status,
                    model,
                    pred_id,
                    ms,
                    (body.get("error") or "")[:200],
                )
                return None
        ms = int((time.perf_counter() - t0) * 1000)
        logger.warning("DETECT replicate_call timeout model=%s id=%s ms=%s", model, pred_id, ms)
        return None
    ms = int((time.perf_counter() - t0) * 1000)
    logger.info(
        "DETECT replicate_call ok model=%s id=%s ms=%s status=%s waited=%s",
        model,
        pred_id,
        ms,
        status,
        bool(output),
    )
    return output


def _masks_from_output(output) -> list[str]:
    if output is None:
        return []
    if isinstance(output, str):
        return [output]
    if isinstance(output, list):
        return [u for u in output if isinstance(u, str)]
    if isinstance(output, dict):
        for key in ("masks", "mask", "output", "annotated"):
            val = output.get(key)
            if isinstance(val, str):
                return [val]
            if isinstance(val, list):
                return [u for u in val if isinstance(u, str)]
    return []


def _load_mask(url_or_data: str, width: int, height: int, client: httpx.Client) -> np.ndarray | None:
    try:
        if url_or_data.startswith("data:"):
            raw = base64.b64decode(url_or_data.split(",", 1)[-1])
        else:
            r = client.get(url_or_data, timeout=60.0)
            if r.status_code >= 400:
                return None
            raw = r.content
        img = Image.open(io.BytesIO(raw)).convert("L")
        if img.size != (width, height):
            img = img.resize((width, height), Image.NEAREST)
        return np.array(img)
    except Exception:
        return None


def _run_prompt_set(
    client: httpx.Client,
    token: str,
    gsam_model: str,
    data_uri: str,
    width: int,
    height: int,
    prompts: list[tuple[str, str]],
) -> list[dict]:
    from app.services.detect_log import format_summary

    collected: list[dict] = []
    for prompt, rtype in prompts:
        logger.info("DETECT grounded_sam class=%s prompt=%r", rtype, prompt[:50])
        output = _replicate_predict(
            client,
            token,
            gsam_model,
            {
                "image": data_uri,
                "mask_prompt": prompt,
                "negative_mask_prompt": "sky, tree, person, car, grass, ground",
            },
        )
        if output is None:
            logger.info("DETECT grounded_sam retry keywords class=%s", rtype)
            output = _replicate_predict(
                client,
                token,
                gsam_model,
                {"image": data_uri, "keywords": prompt},
            )
        if output is None:
            logger.warning("DETECT grounded_sam empty class=%s", rtype)
            continue

        before = len(collected)
        mask_urls = _masks_from_output(output)
        logger.info("DETECT grounded_sam masks class=%s count=%s", rtype, len(mask_urls))
        for mask_url in mask_urls:
            arr = _load_mask(mask_url, width, height, client)
            if arr is None:
                continue
            if float(np.mean(arr > 127)) < 0.001:
                continue
            collected.extend(
                _mask_to_regions(arr, rtype, _pretty_label(rtype, rtype), 0.78, max_parts=12)
            )
        added = collected[before:]
        for r in added:
            r["source"] = "replicate_grounded_sam"
        logger.info(
            "DETECT grounded_sam class_done class=%s added=%s running=%s",
            rtype,
            len(added),
            format_summary(collected),
        )
    return collected


def _maybe_dino(
    client: httpx.Client,
    token: str,
    data_uri: str,
    width: int,
    height: int,
    collected: list[dict],
) -> list[dict]:
    from app.services.detect_log import format_summary

    windows = sum(1 for r in collected if r["region_type"] == RegionType.window.value)
    if windows >= 2:
        logger.info("DETECT grounding_dino skip windows=%s (>=2)", windows)
        return collected
    settings = get_settings()
    dino_model = (settings.replicate_dino_model or "adirik/grounding-dino").strip()
    logger.info("DETECT grounding_dino start windows=%s model=%s", windows, dino_model)
    dino_out = _replicate_predict(
        client,
        token,
        dino_model,
        {
            "image": data_uri,
            "query": "window . door . balcony . railing . pillar . roof",
            "box_threshold": 0.22,
            "text_threshold": 0.18,
        },
    )
    extra = _parse_dino_output(dino_out, width, height)
    logger.info(
        "DETECT grounding_dino done added=%s %s",
        len(extra),
        format_summary(collected + extra),
    )
    return collected + extra


def _detect_grounded_sync(image_path: Path, openings_only: bool = False) -> list[dict]:
    from app.services.detect_log import format_summary

    settings = get_settings()
    token = (settings.replicate_api_token or "").strip()
    if not token:
        raise StructureDetectError(
            "REPLICATE_API_TOKEN is not set. Needed for SegFormer-quality fallback on Replicate."
        )

    data_uri, width, height = _image_data_uri(image_path)
    gsam_model = (settings.replicate_seg_model or "schananas/grounded_sam").strip()
    prompts = _OPENING_PROMPTS if openings_only else _CLASS_PROMPTS
    mode = "openings" if openings_only else "full"
    logger.info(
        "DETECT grounded begin image=%s size=%sx%s mode=%s model=%s prompts=%s",
        image_path.name,
        width,
        height,
        mode,
        gsam_model,
        len(prompts),
    )

    with httpx.Client(timeout=180.0) as client:
        collected = _run_prompt_set(client, token, gsam_model, data_uri, width, height, prompts)
        collected = _maybe_dino(client, token, data_uri, width, height, collected)

    merged = _merge_region_lists(collected)
    if not merged:
        raise StructureDetectError(
            "Replicate Grounded-SAM / Grounding-DINO found no facade parts. "
            "Try another photo or draw regions manually."
        )
    logger.info("DETECT grounded done mode=%s %s", mode, format_summary(merged))
    return merged


def _parse_dino_output(output, width: int, height: int) -> list[dict]:
    regions: list[dict] = []
    if output is None:
        return regions

    detections = []
    if isinstance(output, dict):
        detections = (
            output.get("detections")
            or output.get("boxes")
            or output.get("predictions")
            or output.get("result")
            or []
        )
        if isinstance(detections, dict):
            detections = detections.get("detections") or detections.get("boxes") or []
    elif isinstance(output, list):
        detections = output

    for det in detections:
        if not isinstance(det, dict):
            continue
        label = str(det.get("label") or det.get("phrase") or det.get("text") or "")
        rtype = _label_to_type(label)
        if not rtype:
            continue
        box = det.get("bbox") or det.get("box") or det.get("xyxy") or det.get("coordinates")
        if not box or len(box) < 4:
            continue
        x0, y0, x1, y1 = [float(v) for v in box[:4]]
        if max(x0, y0, x1, y1) > 1.5:
            x0, x1 = x0 / width, x1 / width
            y0, y1 = y0 / height, y1 / height
        x0, y0 = max(0.0, min(1.0, x0)), max(0.0, min(1.0, y0))
        x1, y1 = max(0.0, min(1.0, x1)), max(0.0, min(1.0, y1))
        if x1 - x0 < 0.01 or y1 - y0 < 0.01:
            continue
        regions.append(
            {
                "region_type": rtype,
                "label": _pretty_label(rtype, label),
                "points": [
                    {"x": round(x0, 4), "y": round(y0, 4)},
                    {"x": round(x1, 4), "y": round(y0, 4)},
                    {"x": round(x1, 4), "y": round(y1, 4)},
                    {"x": round(x0, 4), "y": round(y1, 4)},
                ],
                "confidence": float(det.get("confidence") or det.get("score") or 0.7),
                "source": "replicate_grounding_dino",
            }
        )
    return regions


def _label_to_type(label: str) -> str | None:
    key = (label or "").lower()
    if "window" in key:
        return RegionType.window.value
    if any(w in key for w in ("door", "gate", "entrance")):
        return RegionType.gate.value
    if "balcony" in key or "porch" in key:
        return RegionType.balcony.value
    if "roof" in key or "awning" in key or "cornice" in key:
        return RegionType.roof_edge.value
    if "rail" in key or "fence" in key:
        return RegionType.railing.value
    if "pillar" in key or "column" in key:
        return RegionType.pillar.value
    if any(w in key for w in ("wall", "facade", "house", "building")):
        return RegionType.main_wall.value
    return None


async def detect_grounded_regions(image_path: Path, openings_only: bool = False) -> list[dict]:
    return await run_in_threadpool(_detect_grounded_sync, image_path, openings_only)
