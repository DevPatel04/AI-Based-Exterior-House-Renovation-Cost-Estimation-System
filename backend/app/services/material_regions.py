"""Apply user-selected materials onto the correct facade regions.

Uses each region's polygon + assigned Material (and optional texture file)
so redesign always reflects what the user picked for that part.
"""

from __future__ import annotations

import colorsys
import hashlib
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from app.services.storage import absolute_path, ensure_upload_dirs

logger = logging.getLogger(__name__)


@dataclass
class RegionMaterialAssignment:
    region_type: str
    region_label: str
    points: list[dict]  # normalized 0..1 [{x,y}, ...]
    material_id: int
    material_name: str
    material_type: str
    description: str | None = None
    texture_path: str | None = None  # relative upload path


# Distinct, believable finish colors keyed by material wording / type
_TYPE_COLORS: dict[str, tuple[int, int, int]] = {
    "paint": (242, 236, 226),
    "stone_cladding": (196, 168, 132),
    "tiles": (148, 152, 156),
    "texture_finish": (210, 198, 180),
    "glass_railing": (180, 205, 220),
    "metal_railing": (72, 74, 78),
    "panels": (48, 50, 54),
    "other": (190, 186, 180),
}


def color_for_material(name: str, material_type: str) -> tuple[int, int, int]:
    text = f"{name} {material_type}".lower()
    named: list[tuple[tuple[str, ...], tuple[int, int, int]]] = [
        (("warm white", "ivory", "cream", "off white"), (245, 238, 226)),
        (("white",), (248, 246, 242)),
        (("charcoal", "anthracite", "matte black", "black"), (42, 42, 44)),
        (("sandstone", "sand", "beige"), (198, 170, 130)),
        (("grey", "gray"), (150, 152, 156)),
        (("terracotta", "brick", "clay"), (168, 86, 62)),
        (("wood", "teak", "oak", "timber"), (150, 108, 68)),
        (("blue",), (110, 140, 175)),
        (("green",), (95, 125, 100)),
        (("glass", "clear"), (175, 205, 220)),
        (("metal", "ms ", "steel", "powder"), (70, 72, 76)),
        (("acp", "panel", "aluminium", "aluminum"), (55, 58, 62)),
        (("marble", "stone", "granite"), (210, 205, 198)),
        (("rough cast", "texture"), (205, 192, 172)),
    ]
    for keys, rgb in named:
        if any(k in text for k in keys):
            return rgb
    base = _TYPE_COLORS.get(material_type, _TYPE_COLORS["other"])
    # Stable slight variation per material name so different paints don't look identical
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    h, s, v = colorsys.rgb_to_hsv(base[0] / 255, base[1] / 255, base[2] / 255)
    h = (h + (digest[0] - 128) / 2550) % 1.0
    s = min(1.0, max(0.05, s + (digest[1] - 128) / 2000))
    v = min(1.0, max(0.15, v + (digest[2] - 128) / 1800))
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


def _poly_pixels(points: list[dict], width: int, height: int) -> list[tuple[int, int]]:
    coords: list[tuple[int, int]] = []
    for p in points or []:
        try:
            x = int(max(0, min(width - 1, float(p["x"]) * width)))
            y = int(max(0, min(height - 1, float(p["y"]) * height)))
            coords.append((x, y))
        except (KeyError, TypeError, ValueError):
            continue
    return coords


def _tile_texture(tex: Image.Image, size: tuple[int, int]) -> Image.Image:
    tw, th = tex.size
    if tw < 8 or th < 8:
        return Image.new("RGB", size, (180, 180, 180))
    out = Image.new("RGB", size)
    for y in range(0, size[1], th):
        for x in range(0, size[0], tw):
            out.paste(tex, (x, y))
    return out


def _load_texture(rel: str | None, target_tile: int = 256) -> Image.Image | None:
    if not rel:
        return None
    try:
        path = absolute_path(rel)
        if not path.exists():
            return None
        tex = Image.open(path).convert("RGB")
        tex.thumbnail((target_tile, target_tile), Image.Resampling.LANCZOS)
        return tex
    except Exception:
        return None


def build_region_material_prompt(assignments: list[RegionMaterialAssignment], design_name: str = "Design") -> str:
    """Prompt that forces the model to apply EACH selected material to its region only."""
    if not assignments:
        return (
            f"Renovate design “{design_name}” with a clear modern exterior material refresh. "
            "Keep the same building and camera angle. Photoreal photograph."
        )
    lines: list[str] = []
    for i, a in enumerate(assignments, start=1):
        label = a.region_label or a.region_type.replace("_", " ")
        desc = f" ({a.description.strip()})" if (a.description or "").strip() else ""
        lines.append(
            f"{i}) On the {label} region ONLY, apply exactly this material: "
            f"“{a.material_name}” [{a.material_type}]{desc}. "
            f"Do not use any other finish on that part."
        )
    listing = "\n".join(lines)
    return (
        f"EDIT this real exterior photo for design “{design_name}”. "
        "Keep the SAME building, camera angle, window positions, balcony layout, tree, and sky. "
        "Apply the user's selected materials STRICTLY by region — each part must show its assigned finish:\n"
        f"{listing}\n"
        "Make every material change obvious and photoreal (real grain/paint/tile/metal as named). "
        "Do not invent materials the user did not select. Do not swap materials between regions. "
        "Not a cartoon or illustration."
    )


def apply_region_materials(
    source_path: Path,
    assignments: list[RegionMaterialAssignment],
    *,
    opacity: float = 0.82,
) -> str | None:
    """
    Paint each assigned material onto its polygon on the real photo.
    Guarantees the selected material is used on that part (texture if available, else color).
    Returns relative redesign path.
    """
    if not assignments:
        return None
    try:
        base = Image.open(source_path).convert("RGB")
        w, h = base.size
        result = base.copy()
        # Larger regions first so small openings/railings sit on top
        ordered = sorted(
            assignments,
            key=lambda a: abs(_poly_area(a.points)),
            reverse=True,
        )
        for a in ordered:
            coords = _poly_pixels(a.points, w, h)
            if len(coords) < 3:
                logger.warning(
                    "REDESIGN skip region=%s material=%s (need polygon)",
                    a.region_type,
                    a.material_name,
                )
                continue
            color = color_for_material(a.material_name, a.material_type)
            layer = Image.new("RGB", (w, h), color)
            tex = _load_texture(a.texture_path)
            if tex is not None:
                # Scale tile relative to region size for readable texture
                xs = [c[0] for c in coords]
                ys = [c[1] for c in coords]
                rw = max(32, max(xs) - min(xs))
                tile = max(48, min(256, rw // 3))
                tex = tex.resize((tile, tile), Image.Resampling.LANCZOS)
                layer = _tile_texture(tex, (w, h))
                # Nudge texture toward material color so named finishes stay recognizable
                tint = Image.new("RGB", (w, h), color)
                layer = Image.blend(layer, tint, 0.28)

            mask = Image.new("L", (w, h), 0)
            draw = ImageDraw.Draw(mask)
            draw.polygon(coords, fill=int(255 * max(0.35, min(0.95, opacity))))
            # Soft edge so it looks painted onto the facade, not a hard sticker
            mask = mask.filter(ImageFilter.GaussianBlur(radius=max(1, min(w, h) // 250)))

            # Preserve some original shading inside the region (multiply-ish via blend)
            shaded = Image.blend(base, layer, 0.88)
            # Darker materials should keep more shadow from original
            if sum(color) < 180:
                shaded = Image.blend(base, layer, 0.75)
            result = Image.composite(shaded, result, mask)
            logger.info(
                "REDESIGN region_material applied region=%s material=%s color=%s texture=%s",
                a.region_type,
                a.material_name,
                color,
                bool(tex),
            )

        result = ImageEnhance.Sharpness(result).enhance(1.08)
        result = ImageEnhance.Contrast(result).enhance(1.05)
        root = ensure_upload_dirs()
        name = f"{uuid.uuid4().hex}.jpg"
        dest = root / "redesigns" / name
        result.save(dest, format="JPEG", quality=93, optimize=True)
        return f"redesigns/{name}"
    except Exception as exc:
        logger.exception("REDESIGN apply_region_materials failed: %s", exc)
        return None


def _poly_area(points: list[dict]) -> float:
    if not points or len(points) < 3:
        return 0.0
    area = 0.0
    n = len(points)
    for i in range(n):
        j = (i + 1) % n
        try:
            area += float(points[i]["x"]) * float(points[j]["y"])
            area -= float(points[j]["x"]) * float(points[i]["y"])
        except (KeyError, TypeError, ValueError):
            return 0.0
    return abs(area) * 0.5


def mask_ai_to_regions(
    source_path: Path,
    ai_rel: str,
    assignments: list[RegionMaterialAssignment],
    *,
    ai_weight: float = 0.7,
) -> str:
    """
    Keep AI changes mainly inside assigned regions; outside stays the original photo.
    Ensures unassigned parts are not randomly reinvented.
    """
    root = ensure_upload_dirs()
    ai_path = root / ai_rel
    if not ai_path.exists() or not assignments:
        return ai_rel
    try:
        src = Image.open(source_path).convert("RGB")
        ai = Image.open(ai_path).convert("RGB").resize(src.size, Image.Resampling.LANCZOS)
        w, h = src.size
        region_mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(region_mask)
        for a in assignments:
            coords = _poly_pixels(a.points, w, h)
            if len(coords) >= 3:
                draw.polygon(coords, fill=255)
        region_mask = region_mask.filter(ImageFilter.GaussianBlur(max(2, min(w, h) // 200)))
        blended = Image.blend(src, ai, max(0.2, min(0.9, ai_weight)))
        out = Image.composite(blended, src, region_mask)
        name = f"{uuid.uuid4().hex}.jpg"
        dest = root / "redesigns" / name
        out.save(dest, format="JPEG", quality=93, optimize=True)
        return f"redesigns/{name}"
    except Exception as exc:
        logger.warning("REDESIGN mask_ai_to_regions failed: %s", exc)
        return ai_rel
