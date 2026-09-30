from pathlib import Path

import cv2
import numpy as np


def check_image_quality(path: Path) -> tuple[bool, str, int, int]:
    """Soft quality hints only — never blocks upload or further processing."""
    img = cv2.imread(str(path))
    if img is None:
        # Still allow the file; dimensions unknown. Downstream may still work via Pillow.
        return True, "Image uploaded. Tips: use a clear daytime photo of the full facade when possible.", 0, 0

    h, w = img.shape[:2]
    tips: list[str] = []

    if w < 640 or h < 480:
        tips.append(f"Resolution is {w}×{h}; larger photos (ideally 640×480+) usually give better results.")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if blur_score < 50:
        tips.append("Photo looks a bit soft/blurry — a steadier shot in good light helps.")

    brightness = float(np.mean(gray))
    if brightness < 40:
        tips.append("Photo is quite dark — daylight shots work best.")
    elif brightness > 230:
        tips.append("Photo looks very bright/glarey — try avoiding harsh backlight.")

    if tips:
        return True, "Image accepted. " + " ".join(tips), w, h
    return True, "Image looks usable for exterior renovation planning.", w, h
