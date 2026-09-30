import json
import re
from pathlib import Path

from app.core.config import get_settings
from app.models import RegionType


DEFAULT_REGIONS = [
    {
        "region_type": RegionType.main_wall.value,
        "label": "Front wall",
        "points": [{"x": 0.15, "y": 0.25}, {"x": 0.85, "y": 0.25}, {"x": 0.85, "y": 0.85}, {"x": 0.15, "y": 0.85}],
        "confidence": 0.4,
    },
    {
        "region_type": RegionType.window.value,
        "label": "Window left",
        "points": [{"x": 0.22, "y": 0.35}, {"x": 0.38, "y": 0.35}, {"x": 0.38, "y": 0.55}, {"x": 0.22, "y": 0.55}],
        "confidence": 0.35,
    },
    {
        "region_type": RegionType.window.value,
        "label": "Window right",
        "points": [{"x": 0.62, "y": 0.35}, {"x": 0.78, "y": 0.35}, {"x": 0.78, "y": 0.55}, {"x": 0.62, "y": 0.55}],
        "confidence": 0.35,
    },
    {
        "region_type": RegionType.balcony.value,
        "label": "Balcony",
        "points": [{"x": 0.35, "y": 0.55}, {"x": 0.65, "y": 0.55}, {"x": 0.65, "y": 0.72}, {"x": 0.35, "y": 0.72}],
        "confidence": 0.3,
    },
    {
        "region_type": RegionType.gate.value,
        "label": "Entrance / gate",
        "points": [{"x": 0.42, "y": 0.72}, {"x": 0.58, "y": 0.72}, {"x": 0.58, "y": 0.92}, {"x": 0.42, "y": 0.92}],
        "confidence": 0.3,
    },
    {
        "region_type": RegionType.roof_edge.value,
        "label": "Roof edge",
        "points": [{"x": 0.1, "y": 0.12}, {"x": 0.9, "y": 0.12}, {"x": 0.9, "y": 0.22}, {"x": 0.1, "y": 0.22}],
        "confidence": 0.3,
    },
]


def _extract_json(text: str) -> list | dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise


async def gemini_quality_notes(image_path: Path) -> str | None:
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


async def detect_structure_regions(image_path: Path) -> list[dict]:
    """Use Gemini vision when configured; otherwise return editable default regions."""
    settings = get_settings()
    if not settings.gemini_api_key:
        return DEFAULT_REGIONS

    prompt = """
Analyze this residential house exterior photo.
Return ONLY valid JSON array of regions. Each item:
{
  "region_type": one of [main_wall, window, balcony, pillar, parapet, gate, roof_edge, railing, other],
  "label": short string,
  "points": [{"x":0-1,"y":0-1}, ...] normalized polygon (3-8 points),
  "confidence": 0-1
}
Include major walls, windows, balconies, pillars, parapet, gate, roof edges if visible.
"""
    try:
        import google.generativeai as genai

        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel(settings.gemini_model)
        uploaded = genai.upload_file(str(image_path))
        result = model.generate_content([uploaded, prompt])
        data = _extract_json(result.text or "[]")
        if not isinstance(data, list) or not data:
            return DEFAULT_REGIONS
        cleaned = []
        valid_types = {e.value for e in RegionType}
        for item in data:
            rtype = item.get("region_type")
            if rtype not in valid_types:
                continue
            points = item.get("points") or []
            if len(points) < 3:
                continue
            cleaned.append(
                {
                    "region_type": rtype,
                    "label": item.get("label"),
                    "points": points,
                    "confidence": float(item.get("confidence") or 0.5),
                }
            )
        return cleaned or DEFAULT_REGIONS
    except Exception:
        return DEFAULT_REGIONS


def build_redesign_prompt(material_summary: str) -> str:
    return (
        "Photorealistic exterior renovation of this exact residential house. "
        "Preserve building geometry, window/door positions, perspective, and camera angle. "
        f"Apply these materials: {material_summary}. "
        "Natural daylight, realistic textures, no text overlays, no people."
    )
