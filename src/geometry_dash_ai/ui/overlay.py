"""Pure NumPy debug-overlay renderer; it never captures pixels or sends input."""

from __future__ import annotations

from typing import Any

import numpy as np

from geometry_dash_ai.vision.models import GeometryDetection, ScreenBox
from geometry_dash_ai.vision.shadow import ShadowDecision


def render_debug_overlay(
    image: Any,
    player: ScreenBox | None,
    geometry: GeometryDetection,
    shadow: ShadowDecision | None = None,
) -> Any:
    """Return an annotated RGB copy with distinct raw geometry colors."""
    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError("overlay requires a valid RGB/RGBA image")
    rendered = np.ascontiguousarray(image[:, :, :3].copy())
    for box in geometry.floors:
        _rectangle(rendered, box, (80, 255, 80))
    for box in geometry.solids:
        _rectangle(rendered, box, (255, 220, 70))
    for box in geometry.spikes:
        _rectangle(rendered, box, (255, 80, 80))
    if geometry.ceiling is not None:
        _rectangle(rendered, geometry.ceiling, (120, 160, 255))
    if player is not None:
        _rectangle(rendered, player, (255, 80, 255))
        center_x, center_y = (round(value) for value in player.center)
        _crosshair(rendered, center_x, center_y, (255, 255, 255))
        if shadow is not None and shadow.decision is not None:
            _trajectory(rendered, player, shadow)
    return rendered


def _rectangle(image: Any, box: ScreenBox, color: tuple[int, int, int]) -> None:
    height, width, _ = image.shape
    left = max(0, min(width - 1, round(box.x)))
    right = max(left + 1, min(width, round(box.right)))
    top = max(0, min(height - 1, round(box.y)))
    bottom = max(top + 1, min(height, round(box.bottom)))
    image[top : min(top + 2, bottom), left:right] = color
    image[max(top, bottom - 2) : bottom, left:right] = color
    image[top:bottom, left : min(left + 2, right)] = color
    image[top:bottom, max(left, right - 2) : right] = color


def _crosshair(image: Any, x: int, y: int, color: tuple[int, int, int]) -> None:
    height, width, _ = image.shape
    if 0 <= x < width and 0 <= y < height:
        image[max(0, y - 2) : min(height, y + 3), x] = color
        image[y, max(0, x - 2) : min(width, x + 3)] = color


def _trajectory(image: Any, player: ScreenBox, shadow: ShadowDecision) -> None:
    """Draw a bounded selected predicted path in player-relative planner coordinates."""
    assert shadow.decision is not None
    samples = shadow.decision.selected_candidate.trajectory.samples
    # Draw every fourth sample at most; the planner itself caps this at 1,201.
    for sample in samples[::4]:
        x = round(player.x + sample.x + sample.width / 2.0)
        y = round(player.bottom - sample.y - sample.height / 2.0)
        _crosshair(image, x, y, (80, 220, 255))
    collision = shadow.decision.predicted_collision
    if collision is not None:
        _crosshair(
            image,
            round(player.x + collision.x),
            round(player.bottom - collision.y),
            (255, 40, 40),
        )
