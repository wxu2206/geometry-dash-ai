"""Configurable classical player detector for cube and ship color signatures."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from geometry_dash_ai.capture.models import CapturedFrame
from geometry_dash_ai.vision.components import Component, components
from geometry_dash_ai.vision.models import PlayerDetection, PlayerMode, ScreenBox


@dataclass(frozen=True, slots=True)
class PlayerDetectorConfig:
    minimum_pixels: int = 16
    maximum_pixels: int = 10_000
    color_tolerance: int = 72
    cube_color: tuple[int, int, int] = (255, 60, 200)
    ship_color: tuple[int, int, int] = (20, 230, 255)

    def __post_init__(self) -> None:
        if not 1 <= self.minimum_pixels <= self.maximum_pixels <= 100_000:
            raise ValueError("player pixel bounds are invalid")
        if not 1 <= self.color_tolerance <= 255:
            raise ValueError("player color tolerance must be in [1, 255]")
        for color in (self.cube_color, self.ship_color):
            if (
                not isinstance(color, tuple)
                or len(color) != 3
                or any(
                    isinstance(channel, bool)
                    or not isinstance(channel, int)
                    or not 0 <= channel <= 255
                    for channel in color
                )
            ):
                raise ValueError("player colors must be RGB integer tuples")


class ClassicalPlayerDetector:
    """Detect default calibration colors, with unknown mode rather than unsafe guessing."""

    def __init__(self, config: PlayerDetectorConfig | None = None) -> None:
        self._config = config or PlayerDetectorConfig()

    def detect(self, frame: CapturedFrame) -> PlayerDetection | None:
        rgb = frame.image[:, :, :3]
        candidates = (
            (PlayerMode.CUBE, self._config.cube_color),
            (PlayerMode.SHIP, self._config.ship_color),
        )
        detections: list[PlayerDetection] = []
        for mode, color in candidates:
            delta = np.abs(rgb.astype(np.int16) - np.asarray(color, dtype=np.int16))
            mask = np.max(delta, axis=2) <= self._config.color_tolerance
            for component in components(mask, self._config.minimum_pixels):
                if component.area > self._config.maximum_pixels:
                    continue
                detections.append(self._detection(component, mode, frame))
        if not detections:
            return None
        return max(detections, key=lambda item: (item.confidence, -item.bounds.y, -item.bounds.x))

    def _detection(
        self, component: Component, mode: PlayerMode, frame: CapturedFrame
    ) -> PlayerDetection:
        target = max(self._config.minimum_pixels, 64)
        size_confidence = min(1.0, component.area / target)
        aspect = component.width / component.height
        shape_confidence = max(0.0, 1.0 - min(abs(aspect - 1.0), 1.0) * 0.35)
        confidence = min(1.0, 0.55 * size_confidence + 0.45 * shape_confidence)
        return PlayerDetection(
            ScreenBox(
                float(component.x),
                float(component.y),
                float(component.width),
                float(component.height),
            ),
            mode,
            confidence,
            frame.sequence,
            frame.timestamp_ns,
        )
