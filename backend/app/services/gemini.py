import json
import re
from pathlib import Path

from fastapi.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.services.segformer import StructureDetectError


def _extract_json(text: str) -> list | dict:
    text = text.strip()
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


def _refine_regions_gemini_sync(image_path: Path, regions: list[dict]) -> list[dict]:
    """
    Accuracy pass: Gemini adjusts / adds / removes region polygons.
    Only used when GEMINI_API_KEY is set. Does not invent hardcoded defaults.
    """
    settings = get_settings()
    if not (settings.gemini_api_key or "").strip():
        return regions
    if not regions:
        return regions

    valid_types = {
        "main_wall",
        "window",
        "balcony",
        "pillar",
        "parapet",
        "gate",
        "roof_edge",
        "railing",
        "other",
    }
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
  "region_type": one of {sorted(valid_types)},
  "label": short string,
  "points": [{{"x":0-1,"y":0-1}}, ...] polygon with 4-8 points tightly around the part,
  "confidence": 0-1
}}

Rules:
- Fit polygons tightly to visible walls, windows, doors/gates, balconies, pillars, railings, parapet, roof edges.
- Prefer RECALL: include every clearly visible window, door, balcony, railing, pillar, and roof edge.
- Remove only obvious false boxes on sky, trees, ground, or cars.
- Keep the main facade wall as one (or two) polygon(s).
- Separate each window; do not merge all windows into one box.
- If a draft region is roughly correct, keep/adjust it rather than drop it.
- It is better to include a slightly imperfect window box than to miss a window.
"""
    try:
        import google.generativeai as genai

        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel(settings.gemini_model)
        uploaded = genai.upload_file(str(image_path))
        result = model.generate_content([uploaded, prompt])
        data = _extract_json(result.text or "[]")
        if not isinstance(data, list) or not data:
            return regions
        cleaned: list[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            rtype = item.get("region_type")
            if rtype not in valid_types:
                continue
            points = item.get("points") or []
            if len(points) < 3:
                continue
            norm_pts = []
            ok = True
            for p in points[:10]:
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
                    "confidence": float(item.get("confidence") or 0.75),
                    "source": "gemini_refine",
                }
            )
        # Accept refine when it finds at least as many useful parts
        types = {c["region_type"] for c in cleaned}
        draft_parts = sum(1 for r in regions if r.get("region_type") != "main_wall")
        refined_parts = sum(1 for c in cleaned if c["region_type"] != "main_wall")
        if "main_wall" in types and refined_parts >= max(2, draft_parts - 1):
            return cleaned
        # If Gemini returns more openings, prefer it even without perfect wall label
        if refined_parts > draft_parts and refined_parts >= 3:
            return cleaned
        return regions
    except Exception:
        return regions


async def detect_structure_regions(image_path: Path) -> list[dict]:
    """
    Structure detection with accuracy layers:

      1) SegFormer ADE + CMP + OpenCV enrich
      2) Grounded-SAM merge when still missing parts (Replicate)
      3) OpenCV-only fallback if cloud AI unavailable
      4) Gemini refine (when GEMINI_API_KEY set) to tighten boxes
    """
    import logging

    from app.models import RegionType
    from app.services.segformer import detect_opencv_fallback, detect_segformer_regions

    logger = logging.getLogger(__name__)
    last_err: Exception | None = None
    regions: list[dict] = []
    try:
        regions = await detect_segformer_regions(image_path)
    except StructureDetectError as exc:
        last_err = exc
        logger.error("SegFormer detect failed: %s", exc)
    except Exception as exc:
        last_err = StructureDetectError(str(exc))
        logger.exception("SegFormer detect crashed: %s", exc)

    non_wall = sum(1 for r in regions if r.get("region_type") != RegionType.main_wall.value)
    settings = get_settings()
    need_parts = non_wall < 2
    if need_parts and (settings.replicate_api_token or "").strip():
        try:
            from app.services.grounded_detect import detect_grounded_regions
            from app.services.segformer import _merge_region_lists

            grounded = await detect_grounded_regions(image_path)
            regions = _merge_region_lists(regions, grounded)
        except StructureDetectError as exc:
            logger.error("Grounded-SAM detect failed: %s", exc)
            if not regions:
                last_err = exc
        except Exception as exc:
            logger.exception("Grounded-SAM detect crashed: %s", exc)
            if not regions:
                last_err = StructureDetectError(str(exc))

    if not regions:
        try:
            fallback = await run_in_threadpool(detect_opencv_fallback, image_path)
            if fallback:
                if last_err:
                    logger.warning("Cloud detect unavailable (%s); served OpenCV fallback", last_err)
                regions = fallback
        except Exception as exc:
            logger.exception("OpenCV fallback failed: %s", exc)
            last_err = StructureDetectError(str(exc))

    if not regions:
        if last_err:
            raise last_err
        raise StructureDetectError(
            "No structure regions detected. Set HF_TOKEN for SegFormer "
            "(or REPLICATE_API_TOKEN / GEMINI_API_KEY for better accuracy)."
        )

    # Final accuracy pass with Gemini when available
    if (settings.gemini_api_key or "").strip():
        try:
            refined = await run_in_threadpool(_refine_regions_gemini_sync, image_path, regions)
            if refined and len(refined) >= 2:
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
