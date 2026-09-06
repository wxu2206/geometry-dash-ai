"""Fail-closed arming, rate limiting, deadline checks, and stuck-key watchdog."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from geometry_dash_ai.control.backend import ActionBackend, ControlUnavailable


class ControlSafetyError(ControlUnavailable):
    """A request violated the live-control safety envelope."""


@dataclass(frozen=True, slots=True)
class ControlLimits:
    tap_duration_ms: float = 35.0
    maximum_hold_ms: float = 250.0
    maximum_actions_per_second: int = 8
    heartbeat_timeout_ms: float = 250.0
    maximum_session_seconds: float = 1_800.0
    arming_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not 10.0 <= self.tap_duration_ms <= self.maximum_hold_ms <= 1_000.0:
            raise ValueError("tap/hold limits are invalid")
        if not 1 <= self.maximum_actions_per_second <= 20:
            raise ValueError("action rate limit is invalid")
        if not 50.0 <= self.heartbeat_timeout_ms <= 2_000.0:
            raise ValueError("heartbeat timeout is invalid")
        if not 30.0 <= self.maximum_session_seconds <= 7_200.0:
            raise ValueError("control session duration is invalid")
        if not 3.0 <= self.arming_timeout_seconds <= 120.0:
            raise ValueError("arming timeout is invalid")


class GuardedActionController:
    """Own the only path from a planner decision to the action backend."""

    def __init__(self, backend: ActionBackend, limits: ControlLimits | None = None) -> None:
        self._backend = backend
        self._limits = limits or ControlLimits()
        self._armed_at_ns: int | None = None
        self._running_at_ns: int | None = None
        self._session_started_ns: int | None = None
        self._has_started = False
        self._heartbeat_ns: int | None = None
        self._pressed_at_ns: int | None = None
        self._release_due_ns: int | None = None
        self._actions: deque[int] = deque(maxlen=20)
        self._closed = False

    @property
    def armed(self) -> bool:
        return self._armed_at_ns is not None

    @property
    def running(self) -> bool:
        return self._running_at_ns is not None

    @property
    def held(self) -> bool:
        return self._pressed_at_ns is not None

    @property
    def permission_healthy(self) -> bool:
        return self._backend.permission_granted and self._backend.healthy and not self._closed

    def arm(self, now_ns: int) -> None:
        self._require_time(now_ns)
        if self._closed or not self._backend.permission_granted or not self._backend.healthy:
            raise ControlSafetyError("keyboard permission is not healthy; control remains disarmed")
        self._armed_at_ns = now_ns
        self._has_started = False

    def start(self, now_ns: int) -> None:
        self._require_time(now_ns)
        if self._armed_at_ns is None:
            raise ControlSafetyError("live control must be armed before it can start")
        if (
            not self._has_started
            and now_ns - self._armed_at_ns
            > self._seconds_ns(self._limits.arming_timeout_seconds)
        ):
            self.disarm()
            raise ControlSafetyError("live-control arming expired; arm again")
        self._running_at_ns = now_ns
        if self._session_started_ns is None:
            self._session_started_ns = now_ns
        self._has_started = True
        self._heartbeat_ns = now_ns

    def heartbeat(self, now_ns: int) -> None:
        self._require_time(now_ns)
        if self.running:
            self._heartbeat_ns = now_ns

    def tap(self, now_ns: int, decision_deadline_ns: int) -> None:
        self._validate_dispatch(now_ns, decision_deadline_ns)
        if self.held:
            return
        self._rate_limit(now_ns)
        try:
            self._backend.press_action()
        except Exception:
            self.fail_closed()
            raise
        self._pressed_at_ns = now_ns
        self._release_due_ns = now_ns + int(self._limits.tap_duration_ms * 1_000_000.0)

    def set_held(self, held: bool, now_ns: int, decision_deadline_ns: int) -> None:
        self._validate_dispatch(now_ns, decision_deadline_ns)
        if held == self.held:
            return
        self._rate_limit(now_ns)
        try:
            if held:
                self._backend.press_action()
                self._pressed_at_ns = now_ns
                self._release_due_ns = None
            else:
                self._release()
        except Exception:
            self.fail_closed()
            raise

    def tick(self, now_ns: int) -> None:
        self._require_time(now_ns)
        if self._closed:
            return
        if self.held and self._pressed_at_ns is not None:
            maximum = int(self._limits.maximum_hold_ms * 1_000_000.0)
            if self._release_due_ns is not None and now_ns >= self._release_due_ns:
                self._release()
            elif now_ns - self._pressed_at_ns >= maximum:
                self.fail_closed()
                raise ControlSafetyError("maximum action hold exceeded; input released")
        if self.running:
            assert self._session_started_ns is not None and self._heartbeat_ns is not None
            heartbeat_limit = int(self._limits.heartbeat_timeout_ms * 1_000_000.0)
            session_limit = self._seconds_ns(self._limits.maximum_session_seconds)
            if now_ns - self._heartbeat_ns > heartbeat_limit:
                self.fail_closed()
                raise ControlSafetyError("controller heartbeat expired; input released")
            if now_ns - self._session_started_ns > session_limit:
                self.fail_closed()
                raise ControlSafetyError("maximum live-control session expired; input released")

    def pause(self) -> None:
        try:
            self._release()
        except Exception:
            try:
                self._backend.close()
            finally:
                self._closed = True
                self._armed_at_ns = None
            raise
        finally:
            self._running_at_ns = None
            self._heartbeat_ns = None

    def disarm(self) -> None:
        try:
            self.pause()
        finally:
            self._armed_at_ns = None
            self._session_started_ns = None
            self._has_started = False

    def fail_closed(self) -> None:
        try:
            self.disarm()
        except Exception:
            # A failed release means the permission session itself is the final
            # safety boundary. Closing it asks the compositor to release devices.
            try:
                self._backend.close()
            finally:
                self._closed = True

    def close(self) -> None:
        if self._closed:
            return
        self.fail_closed()
        if self._closed:
            return
        try:
            self._backend.close()
        finally:
            self._closed = True

    def _validate_dispatch(self, now_ns: int, deadline_ns: int) -> None:
        self._require_time(now_ns)
        self._require_time(deadline_ns)
        if not self.running:
            raise ControlSafetyError("live control is not running; no input was sent")
        if now_ns > deadline_ns:
            self.fail_closed()
            raise ControlSafetyError("planner decision is stale; input released")
        if not self._backend.healthy:
            self.fail_closed()
            raise ControlSafetyError("keyboard permission was lost; input released")

    def _rate_limit(self, now_ns: int) -> None:
        cutoff = now_ns - 1_000_000_000
        while self._actions and self._actions[0] <= cutoff:
            self._actions.popleft()
        if len(self._actions) >= self._limits.maximum_actions_per_second:
            self.fail_closed()
            raise ControlSafetyError("action rate limit exceeded; input released")
        self._actions.append(now_ns)

    def _release(self) -> None:
        try:
            self._backend.release_action()
        finally:
            self._pressed_at_ns = None
            self._release_due_ns = None

    @staticmethod
    def _require_time(value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("control timestamps must be non-negative integers")

    @staticmethod
    def _seconds_ns(value: float) -> int:
        return int(value * 1_000_000_000.0)
