"""Gemini vision (segmentation / describe) + helpers.

Model guide (paid Gemini API — see Google AI docs):

Image GENERATION / facade edit (must be *-image / Nano Banana):
  BEST quality  → gemini-3-pro-image
  BEST balance  → gemini-3.1-flash-image
  Good fallback → gemini-2.5-flash-image
  DO NOT use    → text-only flash/pro, Imagen (deprecated), TTS/Live/Veo, gemini-2.0-*

STRUCTURE segmentation (bounding boxes — vision reasoning, not image-gen):
  BEST accuracy → gemini-2.5-pro (structured JSON boxes)
  Also good     → gemini-3.1-pro-preview, gemini-3.8-flash
  DO NOT use    → *-image models, flash-lite, Imagen/TTS/Live
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from fastapi.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.services.segformer import StructureDetectError

logger = logging.getLogger(__name__)

_DETECT_PROMPT = """You are a facade structure detector for house renovation.

Detect every visible exterior part of the building in this photo.
Return ONLY a JSON array (no markdown). Each item:
{
  "label": one of ["main_wall","window","gate","balcony","roof_edge","railing","pillar","parapet"],
  "box_2d": [ymin, xmin, ymax, xmax],
  "confidence": number 0 to 1
}

Rules:
- box_2d coordinates are integers normalized to 0-1000 (ymin,xmin,ymax,xmax).
- Include EACH window separately.
- Include the main facade wall once (largest building face).
- Include door/gate if visible.
- Include roof_edge if the roof line is visible.
- Do not invent parts you cannot see.
- Empty array if this is not a building exterior.
"""


def _extract_json(text: str) -> list | dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise


def _gemini_quality_notes_sync(image_path: Path) -> str | None:
    settings = get_settings()
    if not settings.gemini_api_key:
        return None
    try:
        import google.generativeai as genai

        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel(settings.gemini_model)
        uploaded = genai.upload_file(str(image_path))
        result = model.generate_content(
            [
                uploaded,
                "In 2 short sentences, is this a usable exterior photo of a low-rise residential house for renovation planning? Mention any issues.",
            ]
        )
        return (result.text or "").strip()
    except Exception:
        return None


async def gemini_quality_notes(image_path: Path) -> str | None:
    return await run_in_threadpool(_gemini_quality_notes_sync, image_path)


def _box_to_points(box_2d: list, width: int = 1, height: int = 1) -> list[dict] | None:
    """Gemini box_2d is [ymin, xmin, ymax, xmax] in 0..1000 → normalized polygon."""
    try:
        if not isinstance(box_2d, (list, tuple)) or len(box_2d) < 4:
            return None
        ymin, xmin, ymax, xmax = [float(v) for v in box_2d[:4]]
        # Accept 0..1 accidentally
        if max(ymin, xmin, ymax, xmax) <= 1.5:
            ymin, xmin, ymax, xmax = ymin * 1000, xmin * 1000, ymax * 1000, xmax * 1000
        y0 = max(0.0, min(1.0, ymin / 1000.0))
        x0 = max(0.0, min(1.0, xmin / 1000.0))
        y1 = max(0.0, min(1.0, ymax / 1000.0))
        x1 = max(0.0, min(1.0, xmax / 1000.0))
        if x1 - x0 < 0.01 or y1 - y0 < 0.01:
            return None
        return [
            {"x": round(x0, 4), "y": round(y0, 4)},
            {"x": round(x1, 4), "y": round(y0, 4)},
            {"x": round(x1, 4), "y": round(y1, 4)},
            {"x": round(x0, 4), "y": round(y1, 4)},
        ]
    except (TypeError, ValueError):
        return None


def _map_detect_label(raw: str) -> str | None:
    from app.models import RegionType

    key = (raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "wall": RegionType.main_wall.value,
        "main_wall": RegionType.main_wall.value,
        "facade": RegionType.main_wall.value,
        "building": RegionType.main_wall.value,
        "window": RegionType.window.value,
        "windows": RegionType.window.value,
        "door": RegionType.gate.value,
        "gate": RegionType.gate.value,
        "entrance": RegionType.gate.value,
        "balcony": RegionType.balcony.value,
        "roof": RegionType.roof_edge.value,
        "roof_edge": RegionType.roof_edge.value,
        "railing": RegionType.railing.value,
        "pillar": RegionType.pillar.value,
        "column": RegionType.pillar.value,
        "parapet": RegionType.parapet.value,
    }
    if key in aliases:
        return aliases[key]
    for needle, rtype in aliases.items():
        if needle in key:
            return rtype
    return None


def _pretty_detect_label(rtype: str) -> str:
    from app.models import RegionType

    defaults = {
        RegionType.main_wall.value: "Main wall",
        RegionType.window.value: "Window",
        RegionType.gate.value: "Door / gate",
        RegionType.balcony.value: "Balcony",
        RegionType.roof_edge.value: "Roof edge",
        RegionType.railing.value: "Railing",
        RegionType.pillar.value: "Pillar",
        RegionType.parapet.value: "Parapet",
    }
    return defaults.get(rtype, rtype.replace("_", " ").title())


def _parse_gemini_detect_payload(data) -> list[dict]:
    if isinstance(data, dict):
        data = data.get("regions") or data.get("detections") or data.get("items") or []
    if not isinstance(data, list):
        raise StructureDetectError("Gemini detect returned non-list JSON.")

    regions: list[dict] = []
    win_i = 0
    for item in data:
        if not isinstance(item, dict):
            continue
        rtype = _map_detect_label(str(item.get("label") or item.get("region_type") or ""))
        if not rtype:
            continue
        points = _box_to_points(item.get("box_2d") or item.get("bbox") or item.get("box") or [])
        if not points:
            continue
        try:
            conf = float(item.get("confidence") or 0.75)
        except (TypeError, ValueError):
            conf = 0.75
        label = _pretty_detect_label(rtype)
        if rtype == "window":
            win_i += 1
            label = f"Window {win_i}"
        regions.append(
            {
                "region_type": rtype,
                "label": label,
                "points": points,
                "confidence": round(min(0.95, max(0.35, conf)), 3),
                "source": "gemini_detect",
            }
        )
    if not regions:
        raise StructureDetectError("Gemini detect returned no facade regions.")
    return regions


def _gemini_key_invalid_message(resp_text: str = "") -> str | None:
    """Return a user-facing message if Google rejected the API key."""
    low = (resp_text or "").lower()
    if "api_key_invalid" in low or "api key not valid" in low or "api key invalid" in low:
        return (
            "GEMINI_API_KEY invalid — create a Generative Language API key at "
            "https://aistudio.google.com/apikey (usually starts with AIza…) "
            "and set it on Railway"
        )
    if "api_key_service_blocked" in low or "permission_denied" in low and "api key" in low:
        return "GEMINI_API_KEY blocked or missing Generative Language API access"
    return None


def _detect_gemini_sync(image_path: Path) -> list[dict]:
    """Gemini vision structure boxes via REST (inline image + JSON)."""
    import base64
    import io

    import httpx
    from PIL import Image

    settings = get_settings()
    key = (settings.gemini_api_key or "").strip()
    if not key:
        raise StructureDetectError(
            "GEMINI_API_KEY is not set. Add a paid Gemini API key for structure detect."
        )
    if not getattr(settings, "enable_gemini_detect", True):
        raise StructureDetectError("ENABLE_GEMINI_DETECT is false.")
    # Classic AI Studio keys are AIza…; other prefixes often fail on generativelanguage.googleapis.com
    if key.startswith("AQ.") or (len(key) < 20):
        logger.warning(
            "DETECT GEMINI_API_KEY looks non-standard (prefix=%s…) — "
            "use an AI Studio Generative Language key (AIza…)",
            key[:4],
        )

    # Prefer widely available Flash vision models; Pro as optional upgrade
    configured = (settings.gemini_detect_model or "gemini-2.5-flash").strip()
    models: list[str] = []
    for m in (
        configured,
        "gemini-2.5-flash",
        "gemini-3.8-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
    ):
        if m and m not in models:
            models.append(m)

    try:
        pil = Image.open(image_path).convert("RGB")
        pil.thumbnail((1280, 1280))
        buf = io.BytesIO()
        pil.save(buf, format="JPEG", quality=90)
        image_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:
        raise StructureDetectError(f"Could not read image for Gemini detect: {exc}") from exc

    errors: list[str] = []
    with httpx.Client(timeout=90.0) as client:
        for model_name in models:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model_name}:generateContent?key={key}"
            )
            payloads = [
                {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [
                                {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
                                {"text": _DETECT_PROMPT},
                            ],
                        }
                    ],
                    "generationConfig": {
                        "temperature": 0.1,
                        "responseMimeType": "application/json",
                    },
                },
                {
                    "contents": [
                        {
                            "parts": [
                                {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
                                {"text": _DETECT_PROMPT},
                            ]
                        }
                    ],
                    "generationConfig": {"temperature": 0.1},
                },
            ]
            for payload in payloads:
                try:
                    resp = client.post(url, json=payload)
                except Exception as exc:
                    errors.append(f"{model_name}: {exc}"[:160])
                    continue
                if resp.status_code >= 400:
                    bad_key = _gemini_key_invalid_message(resp.text)
                    if bad_key:
                        raise StructureDetectError(bad_key)
                    errors.append(f"{model_name}: HTTP {resp.status_code} {resp.text[:140]}")
                    if resp.status_code in {401, 403, 404}:
                        break
                    continue
                try:
                    body = resp.json()
                except Exception:
                    errors.append(f"{model_name}: non-json")
                    continue
                # Extract text from candidates
                text = ""
                for cand in body.get("candidates") or []:
                    for part in (cand.get("content") or {}).get("parts") or []:
                        if isinstance(part.get("text"), str):
                            text += part["text"]
                if not text.strip():
                    block = (body.get("promptFeedback") or {}).get("blockReason") or "empty"
                    errors.append(f"{model_name}: no text ({block})")
                    continue
                try:
                    data = _extract_json(text.strip())
                    regions = _parse_gemini_detect_payload(data)
                    logger.info("DETECT gemini model=%s regions=%s", model_name, len(regions))
                    return regions
                except Exception as parse_exc:
                    errors.append(f"{model_name}: parse {parse_exc}"[:160])
                    continue

    joined = " | ".join(errors[:3]) if errors else "unknown error"
    bad_key = _gemini_key_invalid_message(joined)
    if bad_key:
        raise StructureDetectError(bad_key)
    raise StructureDetectError("Gemini detect failed: " + joined)


async def detect_gemini_regions(image_path: Path) -> list[dict]:
    return await run_in_threadpool(_detect_gemini_sync, image_path)


async def detect_structure_regions(image_path: Path) -> tuple[list[dict], dict]:
    """
    Detect facade parts (wall, windows, doors, roof, …).

    Order:
      1) Gemini Pro vision boxes (paid — best for open-vocab facade parts)
      2) SegFormer ADE + CMP (HF) + OpenCV enrich
      3) Grounded-SAM (Replicate) when openings scarce
      4) OpenCV-only fallback

    Returns (regions, meta) where meta has primary engine + engines_used.
    """
    from app.models import RegionType
    from app.services.segformer import (
        _merge_region_lists,
        detect_opencv_fallback,
        detect_segformer_regions,
        enrich_with_opencv_parts,
    )

    settings = get_settings()
    last_err: Exception | None = None
    regions: list[dict] = []
    engines_used: list[str] = []
    gemini_note: str | None = None
    has_gemini = bool((settings.gemini_api_key or "").strip()) and getattr(
        settings, "enable_gemini_detect", True
    )
    has_hf = bool((settings.hf_token or "").strip()) and settings.enable_segformer
    has_replicate = bool((settings.replicate_api_token or "").strip())
    min_openings = int(getattr(settings, "grounded_min_openings", 3) or 3)

    if not (settings.gemini_api_key or "").strip():
        gemini_note = "GEMINI_API_KEY not set"
        logger.warning("DETECT %s — will fall back if Gemini required", gemini_note)

    if has_gemini:
        try:
            regions = await detect_gemini_regions(image_path)
            engines_used.append("gemini")
            try:
                from PIL import Image
                import numpy as np

                def _enrich():
                    rgb = np.array(Image.open(image_path).convert("RGB"))
                    return enrich_with_opencv_parts(rgb, regions)

                before = len(regions)
                regions = await run_in_threadpool(_enrich)
                if len(regions) > before and "opencv" not in engines_used:
                    engines_used.append("opencv")
            except Exception as enrich_exc:
                logger.warning("DETECT post-Gemini OpenCV enrich skipped: %s", enrich_exc)
        except StructureDetectError as exc:
            last_err = exc
            gemini_note = str(exc)[:180]
            logger.error("Gemini detect failed: %s", exc)
        except Exception as exc:
            last_err = StructureDetectError(str(exc))
            gemini_note = str(exc)[:180]
            logger.exception("Gemini detect crashed: %s", exc)
    elif getattr(settings, "enable_gemini_detect", True):
        logger.warning("DETECT GEMINI_API_KEY missing / detect disabled — skipping Gemini")

    non_wall = sum(1 for r in regions if r.get("region_type") != RegionType.main_wall.value)
    windows = sum(1 for r in regions if r.get("region_type") == RegionType.window.value)
    need_more = (not regions) or non_wall < min_openings or windows < 2

    if need_more and has_hf:
        try:
            logger.info("DETECT trying SegFormer (need_more=%s)", need_more)
            hf_regs = await detect_segformer_regions(image_path)
            regions = _merge_region_lists(regions, hf_regs)
            engines_used.append("segformer")
        except StructureDetectError as exc:
            last_err = last_err or exc
            logger.error("SegFormer detect failed: %s", exc)
        except Exception as exc:
            last_err = last_err or StructureDetectError(str(exc))
            # HF 410 Gone / DNS failures are common — don't dump full stack
            logger.error("SegFormer detect crashed: %s", exc)
    elif not has_hf and not regions:
        logger.warning("DETECT HF_TOKEN missing — SegFormer skipped")

    non_wall = sum(1 for r in regions if r.get("region_type") != RegionType.main_wall.value)
    windows = sum(1 for r in regions if r.get("region_type") == RegionType.window.value)
    need_parts = (not regions) or non_wall < min_openings or windows < 2

    if need_parts and has_replicate:
        try:
            from app.services.grounded_detect import detect_grounded_regions

            logger.info(
                "DETECT trying Grounded-SAM (non_wall=%s windows=%s)",
                non_wall,
                windows,
            )
            grounded = await detect_grounded_regions(image_path)
            regions = _merge_region_lists(regions, grounded)
            engines_used.append("grounded_sam")
            try:
                from PIL import Image
                import numpy as np

                def _re_enrich():
                    rgb = np.array(Image.open(image_path).convert("RGB"))
                    return enrich_with_opencv_parts(rgb, regions)

                before = len(regions)
                regions = await run_in_threadpool(_re_enrich)
                if len(regions) > before and "opencv" not in engines_used:
                    engines_used.append("opencv")
            except Exception as enrich_exc:
                logger.warning("DETECT post-Grounded OpenCV enrich skipped: %s", enrich_exc)
        except StructureDetectError as exc:
            logger.error("Grounded-SAM detect failed: %s", exc)
            if not regions:
                last_err = exc
        except Exception as exc:
            logger.exception("Grounded-SAM detect crashed: %s", exc)
            if not regions:
                last_err = StructureDetectError(str(exc))

    if regions:
        primary = _primary_engine(regions, engines_used)
        meta = {
            "primary": primary,
            "engines_used": engines_used,
            "region_count": len(regions),
            "gemini_note": gemini_note,
        }
        logger.info("DETECT done primary=%s engines=%s count=%s", primary, engines_used, len(regions))
        return regions, meta

    try:
        fallback = await run_in_threadpool(detect_opencv_fallback, image_path)
        if fallback:
            if last_err:
                logger.warning("Cloud detect unavailable (%s); served OpenCV fallback", last_err)
            engines_used.append("opencv")
            return fallback, {
                "primary": "opencv",
                "engines_used": engines_used,
                "region_count": len(fallback),
                "gemini_note": gemini_note or (str(last_err)[:180] if last_err else None),
            }
    except Exception as exc:
        logger.exception("OpenCV fallback failed: %s", exc)
        last_err = StructureDetectError(str(exc))

    if last_err:
        raise last_err
    raise StructureDetectError(
        "No structure regions detected. Set GEMINI_API_KEY (preferred), "
        "HF_TOKEN for SegFormer, or REPLICATE_API_TOKEN for Grounded-SAM."
    )


def _primary_engine(regions: list[dict], engines_used: list[str]) -> str:
    rank = {
        "gemini_detect": "gemini",
        "gemini": "gemini",
        "cmp": "segformer",
        "ade": "segformer",
        "segformer": "segformer",
        "grounded_sam": "grounded_sam",
        "opencv_enrich": "opencv",
        "opencv_fallback": "opencv",
        "opencv": "opencv",
    }
    # Prefer highest-rank source actually present on regions
    source_rank = {
        "gemini_detect": 100,
        "grounded_sam": 80,
        "cmp": 70,
        "ade": 60,
        "segformer": 50,
        "opencv_enrich": 30,
        "opencv_fallback": 20,
    }
    best_src = None
    best_score = -1
    for r in regions:
        src = (r.get("source") or "").strip()
        score = source_rank.get(src, 0)
        if score > best_score:
            best_score = score
            best_src = src
    if best_src and best_src in rank:
        return rank[best_src]
    if engines_used:
        return engines_used[0]
    return "unknown"


def build_redesign_prompt(material_summary: str) -> str:
    return (
        "EDIT this real exterior photo into a finished renovation — the material change must be "
        "obvious at a glance when compared side-by-side with the original. "
        "Keep the SAME building, camera angle, window positions, balcony, doors, tree, sky, and proportions. "
        "Do NOT invent a new building or change the architecture. "
        "CLEARLY REPLACE the old weathered walls / cladding / finishes with these new materials: "
        f"{material_summary}. "
        "Make walls look freshly renovated: clean new cladding or paint, visible texture "
        "(stone grain, brick mortar, metal panels, wood grain, or render as specified), "
        "remove stains/dirt/decay on renovated surfaces, brighten the facade, "
        "keep windows and openings in the same places but they may get matching new frames/trim. "
        "Photoreal DSLR photograph, natural daylight, sharp real materials — not a painting or cartoon. "
        "The before/after difference should be unmistakable: old tired surface → new premium finish."
    )


def humanize_region_type(region_type: str) -> str:
    return (region_type or "").replace("_", " ").strip() or "facade"
