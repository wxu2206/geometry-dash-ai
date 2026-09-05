"""Small deterministic rendered-pixel fixtures for observe-only perception tests."""

from __future__ import annotations

from typing import Any

import numpy as np

from geometry_dash_ai.capture import CapturedFrame, CaptureRegion
from geometry_dash_ai.vision import PlayerMode

WIDTH = 320
HEIGHT = 180
FLOOR_Y = 140


def scene(
    *,
    mode: PlayerMode = PlayerMode.CUBE,
    player_x: int = 52,
    player_y: int = 116,
    include_player: bool = True,
    include_gap: bool = True,
    include_spike: bool = True,
    include_block: bool = True,
    include_ceiling: bool = True,
    noise: bool = False,
) -> Any:
    image = np.full((HEIGHT, WIDTH, 3), (18, 24, 40), dtype=np.uint8)
    _rectangle(image, 0, FLOOR_Y, 130 if include_gap else WIDTH, 5, (210, 210, 210))
    _rectangle(image, 190 if include_gap else 130, FLOOR_Y, 130, 5, (210, 210, 210))
    if include_ceiling:
        _rectangle(image, 40, 30, 240, 4, (210, 210, 210))
    if include_block:
        _rectangle(image, 220, 92, 36, 48, (220, 220, 220))
    if include_spike:
        _triangle(image, 160, FLOOR_Y, 24, 24, (250, 45, 35))
    if include_player:
        color = (255, 60, 200) if mode is PlayerMode.CUBE else (20, 230, 255)
        _rectangle(image, player_x, player_y, 20, 24, color)
    if noise:
        image[15:20, 10:15] = (80, 90, 100)
        image[80:82, 280:282] = (250, 45, 35)
    return image


def frame(image: Any, sequence: int = 0, timestamp_ns: int = 1_000_000_000) -> CapturedFrame:
    return CapturedFrame(
        np.ascontiguousarray(image),
        timestamp_ns,
        sequence,
        CaptureRegion(0, 0, int(image.shape[1]), int(image.shape[0])),
    )


def _rectangle(
    image: Any, x: int, y: int, width: int, height: int, color: tuple[int, int, int]
) -> None:
    image[y : y + height, x : x + width] = color


def _triangle(
    image: Any, x: int, base_y: int, width: int, height: int, color: tuple[int, int, int]
) -> None:
    for offset in range(height):
        half = max(1, round((offset + 1) * width / (2 * height)))
        center = x + width // 2
        image[base_y - offset - 1, center - half : center + half] = color
