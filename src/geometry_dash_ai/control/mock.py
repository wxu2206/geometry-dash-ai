"""Deterministic action backend for CI and synthetic integration."""

from __future__ import annotations

from geometry_dash_ai.control.backend import ControlPermissionLost


class MockActionBackend:
    def __init__(self, granted: bool = True) -> None:
        self._granted = granted
        self._healthy = granted
        self.held = False
        self.closed = False
        self.events: list[str] = []

    @property
    def permission_granted(self) -> bool:
        return self._granted

    @property
    def healthy(self) -> bool:
        return self._healthy and not self.closed

    def revoke(self) -> None:
        self._healthy = False

    def press_action(self) -> None:
        if not self.healthy:
            raise ControlPermissionLost("mock keyboard permission was revoked")
        self.held = True
        self.events.append("press")

    def release_action(self) -> None:
        if not self.held:
            return
        self.held = False
        self.events.append("release")

    def close(self) -> None:
        self.release_action()
        self.closed = True
