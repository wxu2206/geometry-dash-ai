"""Render synthetic simulator output into the normal perception boundary."""

from __future__ import annotations

import numpy as np

from geometry_dash_ai.capture.models import CapturedFrame, CaptureRegion
from geometry_dash_ai.simulation.models import GameMode, Level, SimulationStatus, StepResult

WIDTH = 320
HEIGHT = 180
FLOOR_Y = 145
SCALE = 0.75


def render_step(
    result: StepResult,
    level: Level,
    sequence: int,
    timestamp_ns: int,
) -> CapturedFrame:
    """Return pixels only; consumers receive no simulator state or level object."""
    image = np.full((HEIGHT, WIDTH, 3), (18, 24, 40), dtype=np.uint8)
    camera = result.camera_x
    for floor in level.floor:
        left = round((floor.start_x - camera) * SCALE)
        right = round((floor.end_x - camera) * SCALE)
        _rect(image, left, FLOOR_Y - round(floor.height * SCALE), right - left, 5, (210, 210, 210))
    _rect(image, 0, 20, WIDTH, 4, (210, 210, 210))
    for block in level.blocks:
        x = round((block.bounds.x - camera) * SCALE)
        width = max(1, round(block.bounds.width * SCALE))
        height = max(1, round(block.bounds.height * SCALE))
        _rect(image, x, FLOOR_Y - height, width, height, (220, 220, 220))
    for spike in level.spikes:
        x = round((spike.x - camera) * SCALE)
        _triangle(
            image,
            x,
            FLOOR_Y - round(spike.base_y * SCALE),
            max(4, round(spike.width * SCALE)),
            max(4, round(spike.height * SCALE)),
        )
    if result.status is SimulationStatus.RUNNING:
        color = (255, 60, 200) if result.state.mode is GameMode.CUBE else (20, 230, 255)
        x = round(result.screen_x * SCALE)
        player_width = max(4, round(24.0 * SCALE))
        player_height = max(4, round(24.0 * SCALE))
        y = FLOOR_Y - round(result.state.y * SCALE) - player_height
        _rect(image, x, y, player_width, player_height, color)
    elif result.status is SimulationStatus.COMPLETE:
        _rect(image, WIDTH // 4, 8, WIDTH // 2, 45, (30, 220, 80))
    return CapturedFrame(
        np.ascontiguousarray(image),
        timestamp_ns,
        sequence,
        CaptureRegion(0, 0, WIDTH, HEIGHT),
    )


def _rect(
    image: np.ndarray, x: int, y: int, width: int, height: int, color: tuple[int, int, int]
) -> None:
    left = max(0, x)
    top = max(0, y)
    right = min(image.shape[1], x + width)
    bottom = min(image.shape[0], y + height)
    if left < right and top < bottom:
        image[top:bottom, left:right] = color


def _triangle(image: np.ndarray, x: int, base_y: int, width: int, height: int) -> None:
    for offset in range(height):
        half = max(1, round((offset + 1) * width / (2 * height)))
        center = x + width // 2
        _rect(image, center - half, base_y - offset - 1, half * 2, 1, (250, 45, 35))
