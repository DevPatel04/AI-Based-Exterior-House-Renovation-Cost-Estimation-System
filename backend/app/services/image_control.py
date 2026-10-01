"""Shared facade-control helpers (Canny edges for ControlNet)."""

from __future__ import annotations

import base64
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def canny_control_png_bytes(source_path: Path, max_side: int = 1024) -> bytes:
    """Build a Canny edge map from the house photo for ControlNet."""
    bgr = cv2.imread(str(source_path))
    if bgr is None:
        rgb = Image.open(source_path).convert("RGB")
        bgr = cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)

    h, w = bgr.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        bgr = cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 80, 180)
    edges = cv2.dilate(edges, np.ones((2, 2), np.uint8), iterations=1)
    edges_rgb = cv2.cvtColor(edges, cv2.COLOR_GRAY2RGB)
    ok, buf = cv2.imencode(".png", edges_rgb)
    if not ok:
        raise RuntimeError("Failed to encode Canny control image")
    return buf.tobytes()


def data_uri_png(png_bytes: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
