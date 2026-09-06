"""Explicit lifecycle state machine for the usable alpha application."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from time import monotonic_ns


class AppState(StrEnum):
    STARTING = "starting"
    SETUP_REQUIRED = "setup_required"
    READY = "ready"
    CAPTURE_CONNECTING = "capture_connecting"
    OBSERVING = "observing"
    SHADOW = "shadow"
    CONTROL_PERMISSION = "control_permission"
    ARMED = "armed"
    RUNNING = "running"
    PAUSED = "paused"
    DEAD = "dead"
    RETRYING = "retrying"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    ERROR = "error"
    STOPPING = "stopping"
    STOPPED = "stopped"


class InvalidTransition(RuntimeError):
    """Raised when an application action is invalid for its current state."""


_TRANSITIONS: dict[AppState, frozenset[AppState]] = {
    AppState.STARTING: frozenset({AppState.SETUP_REQUIRED, AppState.READY, AppState.ERROR}),
    AppState.SETUP_REQUIRED: frozenset(
        {AppState.READY, AppState.CAPTURE_CONNECTING, AppState.ERROR}
    ),
    AppState.READY: frozenset({AppState.CAPTURE_CONNECTING, AppState.CONTROL_PERMISSION}),
    AppState.CAPTURE_CONNECTING: frozenset({AppState.OBSERVING, AppState.DEGRADED, AppState.ERROR}),
    AppState.OBSERVING: frozenset(
        {AppState.SHADOW, AppState.READY, AppState.DEGRADED, AppState.ERROR}
    ),
    AppState.SHADOW: frozenset(
        {AppState.OBSERVING, AppState.CONTROL_PERMISSION, AppState.DEGRADED, AppState.ERROR}
    ),
    AppState.CONTROL_PERMISSION: frozenset({AppState.SHADOW, AppState.ARMED, AppState.ERROR}),
    AppState.ARMED: frozenset(
        {AppState.RUNNING, AppState.SHADOW, AppState.PAUSED, AppState.DEGRADED}
    ),
    AppState.RUNNING: frozenset(
        {AppState.PAUSED, AppState.DEAD, AppState.COMPLETED, AppState.DEGRADED, AppState.ERROR}
    ),
    AppState.PAUSED: frozenset(
        {AppState.RUNNING, AppState.SHADOW, AppState.ARMED, AppState.DEGRADED}
    ),
    AppState.DEAD: frozenset(
        {AppState.RETRYING, AppState.PAUSED, AppState.SHADOW, AppState.COMPLETED}
    ),
    AppState.RETRYING: frozenset({AppState.RUNNING, AppState.PAUSED, AppState.DEGRADED}),
    AppState.COMPLETED: frozenset({AppState.READY}),
    AppState.DEGRADED: frozenset({AppState.CAPTURE_CONNECTING, AppState.OBSERVING, AppState.ERROR}),
    AppState.ERROR: frozenset({AppState.READY}),
    AppState.STOPPING: frozenset({AppState.STOPPED}),
    AppState.STOPPED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class StateTransition:
    previous: AppState
    current: AppState
    reason: str
    timestamp_ns: int


class ApplicationStateMachine:
    """Reject implicit lifecycle changes and permit stopping from every active state."""

    def __init__(self) -> None:
        self._state = AppState.STARTING
        self._last = StateTransition(self._state, self._state, "created", monotonic_ns())

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def last_transition(self) -> StateTransition:
        return self._last

    def transition(self, target: AppState, reason: str) -> StateTransition:
        if not isinstance(target, AppState) or not isinstance(reason, str) or not reason.strip():
            raise ValueError("state transition requires a target and reason")
        if target is AppState.STOPPING and self._state not in {AppState.STOPPING, AppState.STOPPED}:
            return self._set(target, reason)
        if target not in _TRANSITIONS[self._state]:
            raise InvalidTransition(f"cannot transition from {self._state} to {target}")
        return self._set(target, reason)

    def stop(self, reason: str = "stop requested") -> StateTransition:
        if self._state is AppState.STOPPED:
            return self._last
        if self._state is not AppState.STOPPING:
            self.transition(AppState.STOPPING, reason)
        return self.transition(AppState.STOPPED, "shutdown complete")

    def _set(self, target: AppState, reason: str) -> StateTransition:
        transition = StateTransition(self._state, target, reason.strip(), monotonic_ns())
        self._state = target
        self._last = transition
        return transition
