import json
import re
from pathlib import Path

from fastapi.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.models import RegionType
from app.services.segformer import StructureDetectError

_REGION_TYPES = {e.value for e in RegionType}


def _extract_json(text: str) -> list | dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise


def _parse_gemini_regions(data: list | dict, source: str) -> list[dict]:
    if not isinstance(data, list):
        return []
    cleaned: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        rtype = item.get("region_type")
        if rtype not in _REGION_TYPES:
            continue
        points = item.get("points") or []
        if len(points) < 3:
            continue
        norm_pts = []
        ok = True
        for p in points[:12]:
            try:
                x = float(p["x"])
                y = float(p["y"])
            except Exception:
                ok = False
                break
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                ok = False
                break
            norm_pts.append({"x": round(x, 4), "y": round(y, 4)})
        if not ok or len(norm_pts) < 3:
            continue
        cleaned.append(
            {
                "region_type": rtype,
                "label": item.get("label") or rtype.replace("_", " ").title(),
                "points": norm_pts,
                "confidence": float(item.get("confidence") or 0.7),
                "source": source,
            }
        )
    return cleaned


def _gemini_quality_notes_sync(image_path: Path) -> str | None:
    settings = get_settings()
    if not settings.gemini_api_key or not settings.enable_gemini_quality_notes:
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


def _detect_structure_regions_gemini_sync(image_path: Path) -> list[dict]:
    """Full structure detect from the photo via Gemini vision (no template boxes)."""
    settings = get_settings()
    if not (settings.gemini_api_key or "").strip() or not settings.enable_gemini_region_detect:
        return []

    prompt = f"""
Analyze this residential house exterior photo.
Return ONLY a valid JSON array of structure regions. Each item:
{{
  "region_type": one of {sorted(_REGION_TYPES)},
  "label": short string,
  "points": [{{"x":0-1,"y":0-1}}, ...] normalized polygon (3-8 points),
  "confidence": 0-1
}}
Include every visible main wall, window, door/gate, balcony, pillar, parapet, railing, and roof edge.
Do not include sky, trees, ground, or vehicles.
Separate each window; do not merge windows into one polygon.
"""
    try:
        import google.generativeai as genai

        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel(settings.gemini_model)
        uploaded = genai.upload_file(str(image_path))
        result = model.generate_content([uploaded, prompt])
        data = _extract_json(result.text or "[]")
        return _parse_gemini_regions(data, "gemini_vision")
    except Exception:
        return []


def _refine_regions_gemini_sync(image_path: Path, regions: list[dict]) -> list[dict]:
    """Adjust model draft regions using Gemini vision."""
    settings = get_settings()
    if (
        not (settings.gemini_api_key or "").strip()
        or not settings.enable_gemini_region_refine
        or not regions
    ):
        return regions

    seed = [
        {
            "region_type": r.get("region_type"),
            "label": r.get("label"),
            "points": r.get("points"),
            "confidence": r.get("confidence"),
        }
        for r in regions
    ]
    prompt = f"""
You are refining exterior house structure regions for renovation estimating.
Current draft regions (normalized 0-1 image coords) JSON:
{json.dumps(seed)[:6000]}

Return ONLY a JSON array of improved regions. Each item:
{{
  "region_type": one of {sorted(_REGION_TYPES)},
  "label": short string,
  "points": [{{"x":0-1,"y":0-1}}, ...] polygon with 4-8 points tightly around the part,
  "confidence": 0-1
}}

Rules:
- Fit polygons to visible walls, windows, doors/gates, balconies, pillars, railings, parapet, roof edges.
- Include every clearly visible opening; remove only obvious false boxes on sky, trees, ground, or cars.
- Separate each window.
"""
    try:
        import google.generativeai as genai

        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel(settings.gemini_model)
        uploaded = genai.upload_file(str(image_path))
        result = model.generate_content([uploaded, prompt])
        data = _extract_json(result.text or "[]")
        cleaned = _parse_gemini_regions(data, "gemini_refine")
        if not cleaned:
            return regions
        draft_parts = sum(1 for r in regions if r.get("region_type") != RegionType.main_wall.value)
        refined_parts = sum(1 for c in cleaned if c["region_type"] != RegionType.main_wall.value)
        has_wall = any(c["region_type"] == RegionType.main_wall.value for c in cleaned)
        if has_wall and refined_parts >= max(1, draft_parts):
            return cleaned
        if refined_parts > draft_parts and refined_parts >= 2:
            return cleaned
        return regions
    except Exception:
        return regions


async def detect_structure_regions(image_path: Path) -> list[dict]:
    """
    Model-only structure detection (no hardcoded region templates).

      1) SegFormer masks via Hugging Face (best when HF DNS works)
      2) Replicate Grounded-SAM per-class + Grounding-DINO (same accuracy goal when HF fails)
      3) Gemini vision only if ENABLE_GEMINI_REGION_DETECT=true
      4) Gemini refine only if ENABLE_GEMINI_REGION_REFINE=true
    """
    import logging

    from app.services.segformer import _merge_region_lists, detect_segformer_regions

    logger = logging.getLogger(__name__)
    settings = get_settings()
    regions: list[dict] = []
    errors: list[str] = []

    if (settings.hf_token or "").strip() and settings.enable_segformer:
        try:
            regions = await detect_segformer_regions(image_path)
        except StructureDetectError as exc:
            errors.append(str(exc))
            logger.error("HF SegFormer detect failed: %s", exc)
        except Exception as exc:
            errors.append(str(exc))
            logger.exception("HF SegFormer detect crashed: %s", exc)

    non_wall = sum(1 for r in regions if r.get("region_type") != RegionType.main_wall.value)
    windows = sum(1 for r in regions if r.get("region_type") == RegionType.window.value)
    # Enrich whenever SegFormer is missing / wall-heavy (ADE often misses windows)
    need_enrich = (not regions) or non_wall < 2 or windows < 2
    if need_enrich and (settings.replicate_api_token or "").strip():
        try:
            from app.services.grounded_detect import detect_grounded_regions

            # Keep SegFormer wall; only ask Replicate for openings when we already have a wall
            openings_only = bool(regions) and windows < 2
            grounded = await detect_grounded_regions(image_path, openings_only=openings_only)
            regions = _merge_region_lists(regions, grounded) if regions else grounded
        except StructureDetectError as exc:
            errors.append(str(exc))
            logger.error("Replicate detect failed: %s", exc)
        except Exception as exc:
            errors.append(str(exc))
            logger.exception("Replicate detect crashed: %s", exc)

    non_wall = sum(1 for r in regions if r.get("region_type") != RegionType.main_wall.value)
    if (not regions or non_wall < 2) and settings.enable_gemini_region_detect:
        if (settings.gemini_api_key or "").strip():
            try:
                gemini = await run_in_threadpool(_detect_structure_regions_gemini_sync, image_path)
                if gemini:
                    regions = _merge_region_lists(regions, gemini) if regions else gemini
            except Exception as exc:
                errors.append(str(exc))
                logger.exception("Gemini vision detect crashed: %s", exc)

    if not regions:
        primary = errors[0] if errors else ""
        hint = (
            "Detect needs HF_TOKEN (SegFormer) and/or REPLICATE_API_TOKEN "
            "(Grounded-SAM + Grounding-DINO fallback). Or draw regions manually."
        )
        if primary:
            raise StructureDetectError(f"{primary} — {hint}")
        raise StructureDetectError(hint)

    if settings.enable_gemini_region_refine and (settings.gemini_api_key or "").strip():
        try:
            refined = await run_in_threadpool(_refine_regions_gemini_sync, image_path, regions)
            if refined:
                logger.info("Gemini refine: %s → %s regions", len(regions), len(refined))
                return refined
        except Exception as exc:
            logger.warning("Gemini refine skipped: %s", exc)

    return regions


def build_redesign_prompt(material_summary: str) -> str:
    return (
        "Photorealistic exterior renovation of this exact residential house. "
        "Preserve building geometry, window/door positions, perspective, and camera angle. "
        f"Apply these materials: {material_summary}. "
        "Natural daylight, realistic textures, no text overlays, no people."
    )
