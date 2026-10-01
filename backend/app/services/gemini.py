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
    Structure detection (no hardcoded default boxes).

    Order:
      1) SegFormer ADE + CMP (merged) + OpenCV window/door enrich
      2) If still walls-only and Replicate token set → Grounded-SAM merge
    """
    from app.models import RegionType
    from app.services.segformer import detect_segformer_regions

    last_err: Exception | None = None
    regions: list[dict] = []
    try:
        regions = await detect_segformer_regions(image_path)
    except StructureDetectError as exc:
        last_err = exc
    except Exception as exc:
        last_err = StructureDetectError(str(exc))

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
            if not regions:
                last_err = exc
        except Exception as exc:
            if not regions:
                last_err = StructureDetectError(str(exc))

    if regions:
        return regions
    if last_err:
        raise last_err
    raise StructureDetectError(
        "No structure regions detected. Set HF_TOKEN for SegFormer "
        "(or REPLICATE_API_TOKEN for Grounded-SAM backup)."
    )


def build_redesign_prompt(material_summary: str) -> str:
    return (
        "Photorealistic exterior renovation of this exact residential house. "
        "Preserve building geometry, window/door positions, perspective, and camera angle. "
        f"Apply these materials: {material_summary}. "
        "Natural daylight, realistic textures, no text overlays, no people."
    )
