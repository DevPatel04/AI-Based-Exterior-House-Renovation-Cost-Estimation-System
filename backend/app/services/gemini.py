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


async def detect_structure_regions(image_path: Path) -> list[dict]:
    """
    Detect facade parts (wall, windows, doors, roof, …).

    Order:
      1) SegFormer ADE + CMP (when HF_TOKEN set) + OpenCV enrich
      2) Grounded-SAM (Replicate) when openings scarce OR SegFormer unavailable
      3) OpenCV-only fallback
    """
    import logging

    from app.models import RegionType
    from app.services.segformer import detect_opencv_fallback, detect_segformer_regions

    logger = logging.getLogger(__name__)
    settings = get_settings()
    last_err: Exception | None = None
    regions: list[dict] = []
    has_hf = bool((settings.hf_token or "").strip()) and settings.enable_segformer
    has_replicate = bool((settings.replicate_api_token or "").strip())
    min_openings = int(getattr(settings, "grounded_min_openings", 3) or 3)

    if has_hf:
        try:
            regions = await detect_segformer_regions(image_path)
        except StructureDetectError as exc:
            last_err = exc
            logger.error("SegFormer detect failed: %s", exc)
        except Exception as exc:
            last_err = StructureDetectError(str(exc))
            logger.exception("SegFormer detect crashed: %s", exc)
    else:
        logger.warning(
            "DETECT HF_TOKEN missing — SegFormer skipped; using Grounded-SAM / OpenCV"
        )

    non_wall = sum(1 for r in regions if r.get("region_type") != RegionType.main_wall.value)
    windows = sum(1 for r in regions if r.get("region_type") == RegionType.window.value)
    need_parts = (not regions) or non_wall < min_openings or windows < 2

    if need_parts and has_replicate:
        try:
            from app.services.grounded_detect import detect_grounded_regions
            from app.services.segformer import _merge_region_lists, enrich_with_opencv_parts

            logger.info(
                "DETECT trying Grounded-SAM (non_wall=%s windows=%s min=%s hf=%s)",
                non_wall,
                windows,
                min_openings,
                has_hf,
            )
            grounded = await detect_grounded_regions(image_path)
            regions = _merge_region_lists(regions, grounded)
            try:
                from PIL import Image
                import numpy as np

                def _re_enrich():
                    rgb = np.array(Image.open(image_path).convert("RGB"))
                    return enrich_with_opencv_parts(rgb, regions)

                regions = await run_in_threadpool(_re_enrich)
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
        return regions

    try:
        fallback = await run_in_threadpool(detect_opencv_fallback, image_path)
        if fallback:
            if last_err:
                logger.warning("Cloud detect unavailable (%s); served OpenCV fallback", last_err)
            return fallback
    except Exception as exc:
        logger.exception("OpenCV fallback failed: %s", exc)
        last_err = StructureDetectError(str(exc))

    if last_err:
        raise last_err
    raise StructureDetectError(
        "No structure regions detected. Set HF_TOKEN for SegFormer "
        "(or REPLICATE_API_TOKEN for Grounded-SAM backup)."
    )


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
