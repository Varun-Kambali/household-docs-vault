"""Turn a clean page image into something that looks like a phone photo of the paper.

Every printed-line box is pushed through the same perspective transform as the pixels, so the
ground truth still lines up with the text after the warp.
"""

import io
import random
from typing import Literal

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from vault_synth.model import LineBox

Corners = list[tuple[float, float]]


def _coeffs(src: Corners, dst: Corners) -> list[float]:
    """Solve for the 8 perspective coefficients that map dst points to src points (PIL's order)."""
    rows: list[list[float]] = []
    rhs: list[float] = []
    for (x, y), (u, v) in zip(dst, src, strict=True):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs.extend([u, v])
    return [float(c) for c in np.linalg.solve(np.array(rows), np.array(rhs))]


def _apply(c: list[float], x: float, y: float) -> tuple[float, float]:
    d = c[6] * x + c[7] * y + 1
    return (c[0] * x + c[1] * y + c[2]) / d, (c[3] * x + c[4] * y + c[5]) / d


def _move_boxes(lines: list[LineBox], forward: list[float], size: tuple[int, int]) -> list[LineBox]:
    w, h = size
    moved: list[LineBox] = []
    for line in lines:
        x0, y0, x1, y1 = line.bbox
        pts = [
            _apply(forward, px * w, py * h) for px, py in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
        ]
        xs = [min(1.0, max(0.0, p[0] / w)) for p in pts]
        ys = [min(1.0, max(0.0, p[1] / h)) for p in pts]
        moved.append(line.model_copy(update={"bbox": (min(xs), min(ys), max(xs), max(ys))}))
    return moved


def to_photo(
    image: Image.Image,
    lines: list[LineBox],
    rng: random.Random,
    profile: Literal["photo", "scan"] = "photo",
) -> tuple[Image.Image, list[LineBox]]:
    """`photo` is a phone picture of the paper. `scan` is what the Drive scanner makes: corners
    moved a little (at most 1.5% of the width), grayscale, contrast stretched, JPEG quality 80
    and no shadow."""
    w, h = image.size
    src: Corners = [(0, 0), (w, 0), (w, h), (0, h)]
    inward = [(1, 1), (-1, 1), (-1, -1), (1, -1)]
    # Corners only move inward, so the whole sheet stays in frame and the boxes stay inside 0..1.
    reach = 0.015 if profile == "scan" else 0.06
    dst: Corners = [
        (x + sx * rng.uniform(0, reach * w), y + sy * rng.uniform(0, reach * w))
        for (x, y), (sx, sy) in zip(src, inward, strict=True)
    ]
    back = _coeffs(src, dst)  # photo pixel -> page pixel, what PIL's transform wants
    forward = _coeffs(dst, src)  # page pixel -> photo pixel, for the boxes

    if profile == "scan":
        bed = image.convert("RGB").transform(
            (w, h),
            Image.Transform.PERSPECTIVE,
            back,
            Image.Resampling.BICUBIC,
            fillcolor=(255, 255, 255),
        )
        gray = ImageOps.autocontrast(bed.convert("L"), cutoff=1)
        buf = io.BytesIO()
        gray.save(buf, format="JPEG", quality=80)
        scanned = Image.open(io.BytesIO(buf.getvalue())).convert("L")
        return scanned, _move_boxes(lines, forward, (w, h))

    desk = tuple(rng.randint(60, 120) for _ in range(3))
    warped = image.convert("RGB").transform(
        (w, h), Image.Transform.PERSPECTIVE, back, Image.Resampling.BICUBIC, fillcolor=desk
    )

    # Soft shadow falling across the sheet from one side, as from a hand or a lamp.
    arr = np.asarray(warped, dtype=np.float32)
    axis = rng.choice(["x", "y"])
    ramp = np.linspace(rng.uniform(0.72, 0.9), 1.0, w if axis == "x" else h, dtype=np.float32)
    if rng.random() < 0.5:
        ramp = ramp[::-1]
    shade = ramp[None, :, None] if axis == "x" else ramp[:, None, None]
    shaded = np.clip(arr * shade, 0, 255).astype(np.uint8)
    out = Image.fromarray(shaded).filter(ImageFilter.GaussianBlur(rng.uniform(0.6, 1.4)))

    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=rng.randint(70, 85))
    out = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")

    return out, _move_boxes(lines, forward, (w, h))
