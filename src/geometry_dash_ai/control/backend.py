"""Minimal action-only control contracts."""

from __future__ import annotations

from typing import Protocol


class ControlUnavailable(RuntimeError):
    """A user-approved action backend is unavailable."""


class ControlPermissionDenied(ControlUnavailable):
    """The user denied keyboard-control permission."""


class ControlPermissionLost(ControlUnavailable):
    """An approved keyboard-control session ended unexpectedly."""


class ActionBackend(Protocol):
    """The complete alpha input surface: one Geometry Dash action key."""

    @property
    def permission_granted(self) -> bool: ...

    @property
    def healthy(self) -> bool: ...

    def press_action(self) -> None: ...

    def release_action(self) -> None: ...

    def close(self) -> None: ...
