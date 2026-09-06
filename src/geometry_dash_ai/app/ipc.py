"""User-local emergency-stop flag and exclusive live-control lock."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from types import TracebackType


class ControlInstanceBusy(RuntimeError):
    """Another local process owns the live-control lock."""


class LocalRuntimeFiles:
    """No-network IPC restricted to an owner-only runtime directory."""

    def __init__(self, root: Path | None = None) -> None:
        runtime = root
        if runtime is None:
            configured = os.environ.get("XDG_RUNTIME_DIR")
            if not configured:
                raise RuntimeError("XDG_RUNTIME_DIR is unavailable; local stop IPC is disabled")
            runtime = Path(configured) / "geometry-dash-ai"
        if runtime.is_symlink():
            raise RuntimeError("refusing a symlink runtime directory")
        runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(runtime, 0o700)
        self.root = runtime.resolve()
        self.stop_path = self.root / "stop.request"
        self.lock_path = self.root / "control.lock"
        self._lock_descriptor: int | None = None

    def request_stop(self) -> None:
        if self.stop_path.is_symlink():
            raise RuntimeError("refusing a symlink emergency-stop file")
        descriptor = os.open(
            self.stop_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
            0o600,
        )
        try:
            os.write(descriptor, b"STOP\n")
        finally:
            os.close(descriptor)

    def consume_stop(self) -> bool:
        if not self.stop_path.exists():
            return False
        if self.stop_path.is_symlink():
            raise RuntimeError("refusing a symlink emergency-stop file")
        self.stop_path.unlink()
        return True

    def acquire_control(self) -> None:
        if self._lock_descriptor is not None:
            return
        descriptor = os.open(
            self.lock_path,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise ControlInstanceBusy("another Geometry Dash AI process owns live control") from exc
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        self._lock_descriptor = descriptor

    def release_control(self) -> None:
        if self._lock_descriptor is None:
            return
        fcntl.flock(self._lock_descriptor, fcntl.LOCK_UN)
        os.close(self._lock_descriptor)
        self._lock_descriptor = None

    def __enter__(self) -> LocalRuntimeFiles:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release_control()
