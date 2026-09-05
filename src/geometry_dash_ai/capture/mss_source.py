"""Optional ``mss`` screen source with Wayland-safe failure diagnostics."""

from __future__ import annotations

from collections import deque
from time import monotonic_ns
from typing import Any

import numpy as np

from geometry_dash_ai.capture.models import CapturedFrame, CaptureRegion, RgbImage, validate_rate
from geometry_dash_ai.capture.source import CaptureUnavailable


class MssFrameSource:
    """Capture precisely the configured region through the optional user-space mss package."""

    def __init__(self, region: CaptureRegion, target_fps: float = 60.0) -> None:
        self._region = region
        self._target_fps = validate_rate(target_fps)
        self._timestamps: deque[int] = deque(maxlen=120)
        self._sequence = 0
        self._dropped = 0
        self._closed = False
        try:
            import mss

            self._mss: Any = mss.mss()
            self._capture_mapping = self._region_mapping()
        except Exception as exc:
            raise CaptureUnavailable(
                "mss capture is unavailable. On KDE Wayland, grant an approved portal/session "
                "capture permission or use the synthetic backend; no compositor security is "
                "changed."
            ) from exc

    def _region_mapping(self) -> dict[str, int]:
        """Translate an optional monitor-relative rectangle into mss desktop coordinates."""
        mapping = dict(self._region.as_mapping)
        if self._region.monitor is None:
            return mapping
        try:
            monitor = self._mss.monitors[self._region.monitor]
            monitor_left = int(monitor["left"])
            monitor_top = int(monitor["top"])
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise CaptureUnavailable("configured capture monitor is unavailable") from exc
        mapping["left"] += monitor_left
        mapping["top"] += monitor_top
        return mapping

    @property
    def region(self) -> CaptureRegion:
        return self._region

    @property
    def dropped_frames(self) -> int:
        return self._dropped

    @property
    def capture_fps(self) -> float:
        if len(self._timestamps) < 2:
            return 0.0
        elapsed = self._timestamps[-1] - self._timestamps[0]
        return 0.0 if elapsed <= 0 else (len(self._timestamps) - 1) * 1_000_000_000.0 / elapsed

    def capture_once(self) -> CapturedFrame:
        if self._closed:
            raise CaptureUnavailable("capture source is closed")
        try:
            raw = self._mss.grab(self._capture_mapping)
        except Exception as exc:
            raise CaptureUnavailable(
                "screen capture failed. Confirm the selected region and desktop portal permission; "
                "the application remains observe-only."
            ) from exc
        image: RgbImage = np.ascontiguousarray(
            np.asarray(raw, dtype=np.uint8)[:, :, :3][:, :, ::-1]
        )
        timestamp = monotonic_ns()
        frame = CapturedFrame(image, timestamp, self._sequence, self._region)
        self._sequence += 1
        self._timestamps.append(timestamp)
        return frame

    def close(self) -> None:
        if not self._closed:
            self._mss.close()
            self._closed = True
