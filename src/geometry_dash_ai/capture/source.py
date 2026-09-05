"""Capture-source protocols and a latest-only bounded frame buffer."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from geometry_dash_ai.capture.models import CapturedFrame, CaptureRegion, validate_rate


class CaptureUnavailable(RuntimeError):
    """Raised when a desktop backend cannot obtain permission or a frame."""


class FrameSource(Protocol):
    """An observe-only source; implementations have no input-control methods."""

    @property
    def region(self) -> CaptureRegion: ...

    @property
    def capture_fps(self) -> float: ...

    @property
    def dropped_frames(self) -> int: ...

    @property
    def capture_latency_ms(self) -> float: ...

    @property
    def maximum_recent_capture_latency_ms(self) -> float: ...

    def capture_once(self) -> CapturedFrame: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class BufferMetrics:
    published: int
    consumed: int
    dropped: int


class LatestFrameBuffer:
    """Thread-safe bounded buffer that discards stale frames before consumers see them."""

    def __init__(self, capacity: int = 1) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or not 1 <= capacity <= 4:
            raise ValueError("latest frame capacity must be an integer in [1, 4]")
        self._frames: deque[CapturedFrame] = deque(maxlen=capacity)
        self._capacity = capacity
        self._published = 0
        self._consumed = 0
        self._dropped = 0
        self._lock = Lock()

    def publish(self, frame: CapturedFrame) -> None:
        if not isinstance(frame, CapturedFrame):
            raise ValueError("buffer accepts only CapturedFrame instances")
        with self._lock:
            if len(self._frames) == self._capacity:
                self._dropped += 1
            self._frames.append(frame)
            self._published += 1

    def take_latest(self) -> CapturedFrame | None:
        with self._lock:
            if not self._frames:
                return None
            frame = self._frames.pop()
            self._dropped += len(self._frames)
            self._frames.clear()
            self._consumed += 1
            return frame

    @property
    def metrics(self) -> BufferMetrics:
        with self._lock:
            return BufferMetrics(self._published, self._consumed, self._dropped)


def interval_seconds(target_fps: object) -> float:
    """Return a bounded capture cadence; callers remain free to drop late frames."""
    return 1.0 / validate_rate(target_fps)
