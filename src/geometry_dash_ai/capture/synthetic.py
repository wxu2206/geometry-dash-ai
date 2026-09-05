"""Deterministic in-memory frame source for CI and headless observation tests."""

from __future__ import annotations

from time import monotonic_ns
from typing import Any

import numpy as np

from geometry_dash_ai.capture.models import CapturedFrame, CaptureRegion
from geometry_dash_ai.capture.source import CaptureUnavailable


class SyntheticFrameSource:
    """Cycles through supplied RGB frames; it is not a recording or an input backend."""

    def __init__(self, region: CaptureRegion, images: tuple[Any, ...]) -> None:
        if not images:
            raise ValueError("synthetic source requires at least one image")
        self._region = region
        self._images = images
        self._index = 0
        self._closed = False
        self._last_timestamp = 0

    @property
    def region(self) -> CaptureRegion:
        return self._region

    @property
    def capture_fps(self) -> float:
        return 0.0

    @property
    def dropped_frames(self) -> int:
        return 0

    def capture_once(self) -> CapturedFrame:
        if self._closed:
            raise CaptureUnavailable("synthetic source is closed")
        image = np.ascontiguousarray(self._images[self._index % len(self._images)])
        timestamp = max(monotonic_ns(), self._last_timestamp + 1)
        frame = CapturedFrame(image, timestamp, self._index, self._region)
        self._last_timestamp = timestamp
        self._index += 1
        return frame

    def close(self) -> None:
        self._closed = True
