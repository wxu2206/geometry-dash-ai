"""Configurable classical player detector for cube and ship color signatures."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from geometry_dash_ai.capture.models import CapturedFrame
from geometry_dash_ai.vision.components import Component, analysis_scale, components
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

    def detect(
        self, frame: CapturedFrame, prior: ScreenBox | None = None
    ) -> PlayerDetection | None:
        scale = analysis_scale(frame.width, frame.height)
        rgb = frame.image[::scale, ::scale, :3]
        candidates = (
            (PlayerMode.CUBE, self._config.cube_color),
            (PlayerMode.SHIP, self._config.ship_color),
        )
        rgb16 = rgb.astype(np.int16)
        rgb32 = rgb.astype(np.float32)
        brightness = np.maximum(rgb32.mean(axis=2, keepdims=True), 1.0)
        normalized = rgb32 / brightness
        sufficiently_bright = rgb.max(axis=2) >= 50
        detections: list[PlayerDetection] = []
        for mode, color in candidates:
            delta = np.abs(rgb16 - np.asarray(color, dtype=np.int16))
            rgb_match = np.max(delta, axis=2) <= self._config.color_tolerance
            target = np.asarray(color, dtype=np.float32)
            target_normalized = target / max(float(target.mean()), 1.0)
            chroma_distance = np.max(np.abs(normalized - target_normalized), axis=2)
            chroma_match = (chroma_distance <= self._config.color_tolerance / 128.0) & (
                sufficiently_bright
            )
            mask = rgb_match | chroma_match
            minimum_pixels = max(2, self._config.minimum_pixels // (scale * scale))
            maximum_pixels = max(minimum_pixels, self._config.maximum_pixels // (scale * scale))
            for component in components(mask, minimum_pixels):
                if component.area > maximum_pixels:
                    continue
                full_component = Component(
                    component.x * scale,
                    component.y * scale,
                    component.width * scale,
                    component.height * scale,
                    component.area * scale * scale,
                )
                detections.append(self._detection(full_component, mode, frame, prior))
        if not detections:
            return None
        return max(detections, key=lambda item: (item.confidence, -item.bounds.y, -item.bounds.x))

    def _detection(
        self,
        component: Component,
        mode: PlayerMode,
        frame: CapturedFrame,
        prior: ScreenBox | None,
    ) -> PlayerDetection:
        target = max(self._config.minimum_pixels, 64)
        size_confidence = min(1.0, component.area / target)
        aspect = component.width / component.height
        shape_confidence = max(0.0, 1.0 - min(abs(aspect - 1.0), 1.0) * 0.35)
        location_confidence = 0.5
        if prior is not None:
            dx = component.x + component.width / 2.0 - prior.center[0]
            dy = component.y + component.height / 2.0 - prior.center[1]
            distance = (dx * dx + dy * dy) ** 0.5
            location_confidence = max(0.0, 1.0 - distance / max(48.0, prior.width * 4.0))
        confidence = min(
            1.0, 0.45 * size_confidence + 0.35 * shape_confidence + 0.20 * location_confidence
        )
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
