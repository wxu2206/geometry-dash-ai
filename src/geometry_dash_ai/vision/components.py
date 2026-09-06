"""Small bounded connected-component helpers for classical visual heuristics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

MAX_MASK_PIXELS = 100_000
MAX_COMPONENTS = 256


def analysis_scale(width: int, height: int) -> int:
    """Bound classical masks near 400x240 while preserving full-size outputs."""
    return max(1, (width + 399) // 400, (height + 239) // 240)


@dataclass(frozen=True, slots=True)
class Component:
    x: int
    y: int
    width: int
    height: int
    area: int


def components(
    mask: Any, minimum_area: int, maximum_pixels: int = MAX_MASK_PIXELS
) -> tuple[Component, ...]:
    """Return bounded 4-connected components without allocating image-sized labels."""
    if not isinstance(mask, np.ndarray) or mask.ndim != 2 or mask.dtype != np.bool_:
        raise ValueError("component mask must be a two-dimensional bool array")
    if (
        isinstance(minimum_area, bool)
        or not isinstance(minimum_area, int)
        or not 1 <= minimum_area <= MAX_MASK_PIXELS
    ):
        raise ValueError("minimum component area is invalid")
    if (
        isinstance(maximum_pixels, bool)
        or not isinstance(maximum_pixels, int)
        or not 1 <= maximum_pixels <= MAX_MASK_PIXELS
    ):
        raise ValueError("maximum component pixels is invalid")
    if int(np.count_nonzero(mask)) > maximum_pixels:
        return ()
    points = np.argwhere(mask)
    unvisited = {(int(y), int(x)) for y, x in points}
    result: list[Component] = []
    while unvisited and len(result) < MAX_COMPONENTS:
        start = unvisited.pop()
        stack = [start]
        left = right = start[1]
        top = bottom = start[0]
        area = 0
        while stack:
            y, x = stack.pop()
            area += 1
            left = min(left, x)
            right = max(right, x)
            top = min(top, y)
            bottom = max(bottom, y)
            for neighbor in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if neighbor in unvisited:
                    unvisited.remove(neighbor)
                    stack.append(neighbor)
        if area >= minimum_area:
            result.append(Component(left, top, right - left + 1, bottom - top + 1, area))
    return tuple(sorted(result, key=lambda item: (-item.area, item.y, item.x)))
