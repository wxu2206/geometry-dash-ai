"""Bounded local diagnostic frame retention with opt-in event writes."""

from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np

from geometry_dash_ai.capture.models import CapturedFrame

MAX_DIAGNOSTIC_BYTES = 512 * 1024 * 1024


class DiagnosticFrameBuffer:
    """Keeps a fixed recent window in memory; writing is disabled unless explicitly called."""

    def __init__(self, maximum_frames: int = 180) -> None:
        if (
            isinstance(maximum_frames, bool)
            or not isinstance(maximum_frames, int)
            or not 1 <= maximum_frames <= 2_000
        ):
            raise ValueError("diagnostic frame capacity must be in [1, 2000]")
        self._requested_capacity = maximum_frames
        self._frames: deque[CapturedFrame] = deque()
        self._frame_bytes: int | None = None
        self._frame_shape: tuple[int, ...] | None = None

    def append(self, frame: CapturedFrame) -> None:
        if not isinstance(frame, CapturedFrame):
            raise ValueError("diagnostic buffer accepts only captured frames")
        frame_bytes = int(frame.image.nbytes)
        if frame_bytes <= 0 or frame_bytes > MAX_DIAGNOSTIC_BYTES:
            raise ValueError("diagnostic frame exceeds the bounded recording budget")
        if self._frame_bytes is None:
            capacity = max(1, min(self._requested_capacity, MAX_DIAGNOSTIC_BYTES // frame_bytes))
            self._frames = deque(maxlen=capacity)
            self._frame_bytes = frame_bytes
            self._frame_shape = frame.image.shape
        elif frame_bytes != self._frame_bytes or frame.image.shape != self._frame_shape:
            raise ValueError("diagnostic frame dimensions must remain stable within a buffer")
        self._frames.append(frame)

    def recent(self) -> tuple[CapturedFrame, ...]:
        return tuple(self._frames)

    @property
    def capacity(self) -> int:
        return self._frames.maxlen or self._requested_capacity

    def write_event(self, event_name: str, project_root: Path) -> Path:
        """Write bounded compressed frames under ``data/frames`` only when explicitly invoked."""
        if (
            not isinstance(event_name, str)
            or not event_name.replace("_", "").isalnum()
            or len(event_name) > 64
        ):
            raise ValueError("event name must be a short alphanumeric identifier")
        root = project_root.resolve()
        if root != Path.cwd().resolve():
            raise ValueError("diagnostic writes are restricted to the active project root")
        candidate = root / "data" / "frames"
        if candidate.is_symlink() or candidate.parent.is_symlink():
            raise ValueError("diagnostic path cannot traverse symlinks")
        destination = candidate.resolve()
        if root != destination and root not in destination.parents:
            raise ValueError("diagnostic destination escapes project root")
        destination.mkdir(parents=True, exist_ok=True)
        if candidate.is_symlink() or candidate.parent.is_symlink():
            raise ValueError("diagnostic path cannot traverse symlinks")
        payload: object = np.asarray([frame.image for frame in self._frames], dtype=np.uint8)
        timestamps: object = np.asarray(
            [frame.timestamp_ns for frame in self._frames], dtype=np.int64
        )
        path = destination / f"{event_name}.npz"
        np.savez_compressed(path, frames=payload, timestamps_ns=timestamps)
        return path
