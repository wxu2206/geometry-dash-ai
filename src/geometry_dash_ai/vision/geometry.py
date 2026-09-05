"""Bounded classical local-geometry detection for high-contrast gameplay views."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from geometry_dash_ai.capture.models import CapturedFrame
from geometry_dash_ai.vision.components import Component, components
from geometry_dash_ai.vision.models import GeometryDetection, PlayerDetection, ScreenBox


@dataclass(frozen=True, slots=True)
class GeometryDetectorConfig:
    minimum_area_px: int = 16
    minimum_floor_width_px: int = 24

    def __post_init__(self) -> None:
        if not 1 <= self.minimum_area_px <= 10_000 or not 1 <= self.minimum_floor_width_px <= 7_680:
            raise ValueError("geometry detector bounds are invalid")


class ClassicalGeometryDetector:
    """Find bright floor/platform shapes and red triangular-hazard candidates.

    This deliberately favors conservative high-confidence detections over trying
    to classify every decorated Geometry Dash object.
    """

    def __init__(self, config: GeometryDetectorConfig | None = None) -> None:
        self._config = config or GeometryDetectorConfig()

    def detect(self, frame: CapturedFrame, player: PlayerDetection | None) -> GeometryDetection:
        rgb = frame.image[:, :, :3]
        brightness = rgb.max(axis=2)
        bright = (brightness >= 170) & (rgb.min(axis=2) >= 90)
        if player is not None:
            self._erase_box(bright, player.bounds)
        floors, floor_rows = self._horizontal_segments(bright, lower_half=True)
        ceiling_segments, ceiling_rows = self._horizontal_segments(bright, lower_half=False)
        object_mask = bright.copy()
        for row in (*floor_rows, *ceiling_rows):
            object_mask[max(0, row - 2) : min(object_mask.shape[0], row + 3), :] = False
        solids = tuple(
            self._box_from_component(item)
            for item in components(object_mask, self._config.minimum_area_px)
        )
        red = (
            (rgb[:, :, 0].astype(np.int16) - rgb[:, :, 1].astype(np.int16) >= 80)
            & (rgb[:, :, 0].astype(np.int16) - rgb[:, :, 2].astype(np.int16) >= 80)
            & (rgb[:, :, 0] >= 150)
        )
        spikes = tuple(
            self._box_from_component(item)
            for item in components(red, self._config.minimum_area_px)
            if item.width >= 3 and item.height >= 3
        )
        ceiling = ceiling_segments[0] if ceiling_segments else None
        items = len(floors) + len(solids) + len(spikes) + (1 if ceiling else 0)
        confidence = min(1.0, items / 4.0) if items else 0.0
        return GeometryDetection(floors, solids, spikes, ceiling, confidence)

    def _horizontal_segments(
        self, mask: np.ndarray, *, lower_half: bool
    ) -> tuple[tuple[ScreenBox, ...], tuple[int, ...]]:
        height, width = mask.shape
        start, end = (height // 2, height) if lower_half else (0, height // 2)
        counts = mask[start:end].sum(axis=1)
        candidates = (
            np.where(counts >= max(self._config.minimum_floor_width_px, width // 5))[0] + start
        )
        if not len(candidates):
            return (), ()
        row = int(candidates[-1] if lower_half else candidates[0])
        runs: list[ScreenBox] = []
        line = mask[row]
        run_start: int | None = None
        enabled: object
        for x, enabled in enumerate(np.append(line, False)):
            if enabled and run_start is None:
                run_start = x
            if not enabled and run_start is not None:
                if x - run_start >= self._config.minimum_floor_width_px:
                    runs.append(ScreenBox(float(run_start), float(row), float(x - run_start), 2.0))
                run_start = None
        return tuple(runs), (row,)

    @staticmethod
    def _erase_box(mask: np.ndarray, box: ScreenBox) -> None:
        left = max(0, int(box.x))
        right = min(mask.shape[1], int(box.right) + 1)
        top = max(0, int(box.y))
        bottom = min(mask.shape[0], int(box.bottom) + 1)
        mask[top:bottom, left:right] = False

    @staticmethod
    def _box_from_component(component: Component) -> ScreenBox:
        if not isinstance(component, Component):
            raise ValueError("invalid geometry component")
        return ScreenBox(
            float(component.x), float(component.y), float(component.width), float(component.height)
        )
