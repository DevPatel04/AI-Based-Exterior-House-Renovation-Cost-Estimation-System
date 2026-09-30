from pathlib import Path

import cv2
import numpy as np


def check_image_quality(path: Path) -> tuple[bool, str, int, int]:
    """OpenCV-based quality gate: resolution + blur."""
    img = cv2.imread(str(path))
    if img is None:
        return False, "Could not read image. Please upload a JPG or PNG of your house exterior.", 0, 0

    h, w = img.shape[:2]
    if w < 640 or h < 480:
        return (
            False,
            f"Image too small ({w}x{h}). Use at least 640x480 and capture the full facade clearly.",
            w,
            h,
        )

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if blur_score < 50:
        return (
            False,
            "Image looks too blurry. Retake in good light, hold the camera steady, and face the house squarely.",
            w,
            h,
        )

    brightness = float(np.mean(gray))
    if brightness < 40:
        return False, "Image is too dark. Retake outdoors in daylight if possible.", w, h
    if brightness > 230:
        return False, "Image is overexposed. Avoid harsh glare and retake.", w, h

    return True, "Image looks usable for exterior renovation planning.", w, h
