"""Central live-runtime safety supervisor and mode-specific controller routing."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic_ns

from geometry_dash_ai.app.models import DashboardSnapshot, Readiness, readiness_from_snapshot
from geometry_dash_ai.app.state import ApplicationStateMachine, AppState
from geometry_dash_ai.control.backend import ActionBackend
from geometry_dash_ai.control.guarded import ControlLimits, GuardedActionController
from geometry_dash_ai.learning import PhysicsCalibration
from geometry_dash_ai.physics import CubePhysicsParameters
from geometry_dash_ai.physics.ship import ShipPhysicsParameters, ShipState
from geometry_dash_ai.planning import CubePlannerConfig
from geometry_dash_ai.planning.ship import ShipDecision, plan_ship_action
from geometry_dash_ai.telemetry import RunHistoryStore, RunSummary
from geometry_dash_ai.vision.models import PlayerMode
from geometry_dash_ai.vision.pipeline import PerceptionSnapshot
from geometry_dash_ai.vision.planner_preview import preview_cube_plan
from geometry_dash_ai.vision.run_state import RunObservation, RunPhase, VisualRunStateObserver
from geometry_dash_ai.vision.shadow import ShadowDecision


@dataclass(frozen=True, slots=True)
class SupervisorLimits:
    decision_maximum_age_ms: float = 100.0
    maximum_attempts: int = 25
    retry_cooldown_seconds: float = 1.0

    def __post_init__(self) -> None:
        if not 20.0 <= self.decision_maximum_age_ms <= 500.0:
            raise ValueError("decision age limit is invalid")
        if not 1 <= self.maximum_attempts <= 200:
            raise ValueError("attempt limit is invalid")
        if not 0.25 <= self.retry_cooldown_seconds <= 10.0:
            raise ValueError("retry cooldown is invalid")


class RuntimeSupervisor:
    """Own lifecycle, readiness, planning, action scheduling, and cleanup."""

    def __init__(
        self,
        *,
        setup_complete: bool,
        limits: SupervisorLimits | None = None,
        run_history: RunHistoryStore | None = None,
        physics_ready: bool = True,
        cube_physics: CubePhysicsParameters | None = None,
        cube_planner: CubePlannerConfig | None = None,
        action_latency_seconds: float = 0.04,
    ) -> None:
        self.state = ApplicationStateMachine()
        self.limits = limits or SupervisorLimits()
        self.state.transition(
            AppState.READY if setup_complete else AppState.SETUP_REQUIRED,
            "configuration validated" if setup_complete else "first-run setup is required",
        )
        self._controller: GuardedActionController | None = None
        self._run_history = run_history
        self._physics_ready = physics_ready
        self._cube_physics = cube_physics or CubePhysicsParameters()
        self._cube_planner = cube_planner or CubePlannerConfig()
        if not 0.0 <= action_latency_seconds <= 0.5:
            raise ValueError("action latency is outside bounds")
        self._action_latency_seconds = action_latency_seconds
        self._run_observer = VisualRunStateObserver()
        self._attempt = 0
        self._last_mode = PlayerMode.UNKNOWN
        self._last_planner_ns: int | None = None
        self._planner_hz = 0.0
        self._planner_confidence = 0.0
        self._predicted_action = "NONE"
        self._risk = "unknown"
        self._last_error: str | None = None
        self._last_death_ns: int | None = None
        self._retry_started_ns: int | None = None
        self._attempt_started_ns: int | None = None
        self._cube_shadow: ShadowDecision | None = None
        self._ship_shadow: ShipDecision | None = None

    @property
    def controller(self) -> GuardedActionController | None:
        return self._controller

    def begin_capture(self) -> None:
        self.state.transition(AppState.CAPTURE_CONNECTING, "requesting capture permission")

    def setup_completed(self) -> None:
        if self.state.state is not AppState.SETUP_REQUIRED:
            raise RuntimeError("setup completion is only valid during first-run setup")
        self.state.transition(AppState.READY, "validated local configuration saved")

    def capture_ready(self) -> None:
        self.state.transition(AppState.OBSERVING, "capture stream is healthy")

    def enter_shadow(self) -> None:
        self.state.transition(AppState.SHADOW, "shadow mode selected")

    def attach_control(self, backend: ActionBackend, limits: ControlLimits | None = None) -> None:
        if self.state.state is not AppState.SHADOW:
            raise RuntimeError("live-control permission may only be requested from Shadow mode")
        self.state.transition(AppState.CONTROL_PERMISSION, "requesting keyboard-only permission")
        if not backend.permission_granted or not backend.healthy:
            backend.close()
            self.state.transition(AppState.SHADOW, "keyboard permission was not granted")
            raise RuntimeError("keyboard permission was not granted; no input was enabled")
        self._controller = GuardedActionController(backend, limits)
        self.state.transition(AppState.SHADOW, "keyboard permission granted; not armed")

    def arm(self, now_ns: int, readiness: Readiness) -> None:
        if self.state.state is not AppState.SHADOW or self._controller is None:
            raise RuntimeError("Shadow mode and keyboard permission are required before arming")
        if not readiness.ready:
            raise RuntimeError(f"live readiness failed: {', '.join(readiness.failures)}")
        self.state.transition(AppState.CONTROL_PERMISSION, "arming requested")
        self._controller.arm(now_ns)
        self.state.transition(AppState.ARMED, "live AI armed; waiting for explicit start")

    def readiness(self, snapshot: PerceptionSnapshot, now_ns: int) -> Readiness:
        return readiness_from_snapshot(
            snapshot,
            now_ns,
            control_healthy=(
                self._controller is not None and self._controller.permission_healthy
            ),
            physics_ready=self._physics_ready,
            planner_healthy=True,
            maximum_frame_age_ms=self.limits.decision_maximum_age_ms,
        )

    def start(self, now_ns: int) -> None:
        if self.state.state is not AppState.ARMED or self._controller is None:
            raise RuntimeError("live AI is not armed")
        self._controller.start(now_ns)
        self._attempt += 1
        self._attempt_started_ns = now_ns
        self.state.transition(AppState.RUNNING, "explicit live AI start")

    def process(
        self,
        snapshot: PerceptionSnapshot,
        now_ns: int | None = None,
        *,
        completion_visual_cue: bool = False,
    ) -> tuple[Readiness, RunObservation]:
        now = monotonic_ns() if now_ns is None else now_ns
        controller_healthy = self._controller is not None and self._controller.running
        readiness = readiness_from_snapshot(
            snapshot,
            now,
            control_healthy=controller_healthy,
            physics_ready=self._physics_ready,
            planner_healthy=True,
            maximum_frame_age_ms=self.limits.decision_maximum_age_ms,
        )
        run = self._run_observer.update(snapshot, completion_visual_cue=completion_visual_cue)
        if self.state.state is AppState.RETRYING:
            assert self._controller is not None
            self._controller.heartbeat(now)
            self._controller.tick(now)
            if run.phase is RunPhase.ACTIVE:
                self._attempt += 1
                self._attempt_started_ns = now
                self._retry_started_ns = None
                self.state.transition(AppState.RUNNING, "visual restart confirmed")
            elif (
                self._retry_started_ns is not None
                and now - self._retry_started_ns > 3_000_000_000
            ):
                self._controller.pause()
                self._last_error = "visual retry confirmation timed out"
                self.state.transition(AppState.PAUSED, "visual retry confirmation timed out")
            return readiness, run
        if self.state.state is not AppState.RUNNING:
            return readiness, run
        assert self._controller is not None
        if run.phase is RunPhase.COMPLETE:
            self._controller.disarm()
            self._record_run(snapshot, now, "complete", None)
            self.state.transition(AppState.COMPLETED, "visual completion confirmed")
            return readiness, run
        if run.phase is RunPhase.DEAD:
            self._controller.pause()
            self._last_death_ns = now
            self._record_run(
                snapshot,
                now,
                "dead",
                None if run.death_cause is None else run.death_cause.value,
            )
            self.state.transition(AppState.DEAD, "visual death confirmed")
            return readiness, run
        if not readiness.ready:
            self._fail_closed(f"live readiness lost: {', '.join(readiness.failures)}")
            return readiness, run
        try:
            self._plan_and_dispatch(snapshot, now)
            self._controller.heartbeat(now)
            self._controller.tick(now)
        except Exception as exc:
            self._fail_closed(f"controller/planner error: {exc}")
        return readiness, run

    def set_physics_ready(self, ready: bool) -> None:
        self._physics_ready = bool(ready)

    def set_cube_calibration(self, calibration: PhysicsCalibration) -> None:
        self._cube_physics = CubePhysicsParameters(
            gravity=calibration.gravity,
            jump_velocity=calibration.jump_velocity,
            horizontal_speed=calibration.horizontal_speed,
            collision_width=calibration.collision_width,
            collision_height=calibration.collision_height,
        )
        self._action_latency_seconds = calibration.action_latency_seconds
        self._physics_ready = calibration.sample_count > 0

    @property
    def cube_shadow(self) -> ShadowDecision | None:
        return self._cube_shadow

    @property
    def ship_shadow(self) -> ShipDecision | None:
        return self._ship_shadow

    def plan_shadow(self, snapshot: PerceptionSnapshot) -> None:
        """Update planner diagnostics without crossing the action boundary."""
        if self.state.state not in {AppState.SHADOW, AppState.ARMED, AppState.PAUSED}:
            return
        started = monotonic_ns()
        player = snapshot.tracked_player
        if player.mode is PlayerMode.CUBE:
            cube_decision = preview_cube_plan(
                snapshot,
                self._cube_physics,
                self._cube_planner,
            )
            self._cube_shadow = ShadowDecision(
                cube_decision,
                snapshot.frame.sequence,
                snapshot.frame.timestamp_ns,
            )
            self._ship_shadow = None
            if cube_decision is not None:
                self._planner_confidence = cube_decision.confidence
                self._predicted_action = self._cube_shadow.recommendation
                self._risk = (
                    "collision" if cube_decision.predicted_collision else "safe"
                )
        elif player.mode is PlayerMode.SHIP:
            ship_decision = self._ship_decision(snapshot)
            self._ship_shadow = ship_decision
            self._cube_shadow = None
            self._planner_confidence = ship_decision.confidence
            self._predicted_action = "HOLD" if ship_decision.hold else "RELEASE"
            self._risk = "collision" if ship_decision.all_candidates_unsafe else "safe"
        else:
            self._cube_shadow = None
            self._ship_shadow = None
            self._planner_confidence = 0.0
            self._predicted_action = "NO RECOMMENDATION"
            self._risk = "unknown"
        self._update_planner_rate(started)

    def retry(self, now_ns: int) -> None:
        if self.state.state is not AppState.DEAD or self._controller is None:
            raise RuntimeError("retry requires a visually confirmed death")
        if self._attempt >= self.limits.maximum_attempts:
            self._controller.disarm()
            self.state.transition(AppState.SHADOW, "attempt limit reached; re-arm explicitly")
            raise RuntimeError("attempt limit reached")
        if self._last_death_ns is None or now_ns - self._last_death_ns < int(
            self.limits.retry_cooldown_seconds * 1_000_000_000.0
        ):
            raise RuntimeError("retry cooldown has not elapsed")
        self.state.transition(AppState.RETRYING, "visual reset action requested")
        self._run_observer.reset_for_retry()
        self._controller.start(now_ns)
        self._controller.tap(now_ns, now_ns + 50_000_000)
        self._controller.heartbeat(now_ns)
        self._retry_started_ns = now_ns

    def maybe_retry(self, now_ns: int) -> bool:
        """Retry only after visual death, cooldown, and within the attempt limit."""
        if self.state.state is not AppState.DEAD or self._last_death_ns is None:
            return False
        if self._attempt >= self.limits.maximum_attempts:
            assert self._controller is not None
            self._controller.disarm()
            self._last_error = "attempt limit reached"
            self.state.transition(AppState.SHADOW, "attempt limit reached; re-arm explicitly")
            return False
        cooldown = int(self.limits.retry_cooldown_seconds * 1_000_000_000.0)
        if now_ns - self._last_death_ns < cooldown:
            return False
        self.retry(now_ns)
        return True

    def pause(self, reason: str = "user paused live AI") -> None:
        if self._controller is not None:
            self._controller.pause()
        if self.state.state is AppState.RUNNING:
            self.state.transition(AppState.PAUSED, reason)

    def resume(self, now_ns: int) -> None:
        if self.state.state is not AppState.PAUSED or self._controller is None:
            raise RuntimeError("live AI is not paused")
        self._controller.start(now_ns)
        self.state.transition(AppState.RUNNING, "user resumed live AI")

    def emergency_stop(self) -> None:
        if self._controller is not None:
            self._controller.close()
        self.state.stop("EMERGENCY STOP")

    def degrade(self, reason: str) -> None:
        if self._controller is not None:
            self._controller.fail_closed()
        current = self.state.state
        if current in {
            AppState.CAPTURE_CONNECTING,
            AppState.OBSERVING,
            AppState.SHADOW,
            AppState.ARMED,
            AppState.RUNNING,
            AppState.PAUSED,
            AppState.RETRYING,
        }:
            self.state.transition(AppState.DEGRADED, reason)
        self._last_error = reason

    def close(self) -> None:
        if self._controller is not None:
            self._controller.close()
        self.state.stop("application shutdown")

    def dashboard(self, snapshot: PerceptionSnapshot | None = None) -> DashboardSnapshot:
        player = None if snapshot is None else snapshot.tracked_player
        geometry = None if snapshot is None else snapshot.fused_geometry
        perception_fps = 0.0 if snapshot is None else snapshot.metrics.processing_fps
        latency = 0.0 if snapshot is None else snapshot.metrics.processing_latency_ms
        if self._controller is not None and self._controller.running:
            control_status = "running"
        elif self._controller is not None and self._controller.permission_healthy:
            control_status = (
                "permission granted — armed"
                if self.state.state is AppState.ARMED
                else "permission granted — not armed"
            )
        else:
            control_status = "not granted"
        return DashboardSnapshot(
            status=self.state.state.value.upper(),
            capture_status="healthy" if snapshot is not None else "not connected",
            control_status=control_status,
            ai_mode=self.state.state.value,
            game_mode="unknown" if player is None else player.mode.value,
            attempt=self._attempt,
            capture_fps=0.0,
            perception_fps=perception_fps,
            planner_hz=self._planner_hz,
            latency_ms=latency,
            player_confidence=0.0 if player is None else player.confidence,
            geometry_confidence=0.0 if geometry is None else geometry.confidence,
            planner_confidence=self._planner_confidence,
            physics_ready=self._physics_ready,
            predicted_action=self._predicted_action,
            risk=self._risk,
            last_error=self._last_error,
        )

    def _plan_and_dispatch(self, snapshot: PerceptionSnapshot, now_ns: int) -> None:
        assert self._controller is not None
        if self._last_mode is not snapshot.tracked_player.mode:
            self._controller.set_held(False, now_ns, now_ns + 1)
            self._last_mode = snapshot.tracked_player.mode
        deadline = snapshot.frame.timestamp_ns + int(
            self.limits.decision_maximum_age_ms * 1_000_000.0
        )
        started = monotonic_ns()
        if snapshot.tracked_player.mode is PlayerMode.CUBE:
            cube_decision = preview_cube_plan(
                snapshot,
                self._cube_physics,
                self._cube_planner,
            )
            if cube_decision is None:
                raise RuntimeError("cube planner has no reliable decision")
            self._cube_shadow = ShadowDecision(
                cube_decision,
                snapshot.frame.sequence,
                snapshot.frame.timestamp_ns,
            )
            self._ship_shadow = None
            self._planner_confidence = cube_decision.confidence
            self._risk = (
                "collision" if cube_decision.predicted_collision is not None else "safe"
            )
            latency_frames = round(
                self._action_latency_seconds / self._cube_physics.time_step
            )
            if (
                cube_decision.jump_delay_frames is not None
                and cube_decision.jump_delay_frames <= latency_frames
            ):
                self._controller.tap(now_ns, deadline)
                self._predicted_action = (
                    "JUMP NOW"
                    if cube_decision.jump_delay_frames == 0
                    else f"JUMP NOW (latency for +{cube_decision.jump_delay_frames})"
                )
            else:
                self._predicted_action = (
                    "WAIT"
                    if cube_decision.jump_delay_frames is None
                    else f"JUMP +{cube_decision.jump_delay_frames} frames"
                )
        elif snapshot.tracked_player.mode is PlayerMode.SHIP:
            ship_decision = self._ship_decision(snapshot)
            self._ship_shadow = ship_decision
            self._cube_shadow = None
            self._controller.set_held(ship_decision.hold, now_ns, deadline)
            self._planner_confidence = ship_decision.confidence
            self._predicted_action = "HOLD" if ship_decision.hold else "RELEASE"
            self._risk = "collision" if ship_decision.all_candidates_unsafe else "safe"
        else:
            raise RuntimeError("unknown game mode")
        finished = self._update_planner_rate(started)
        if finished - started > int(self.limits.decision_maximum_age_ms * 1_000_000.0):
            raise RuntimeError("planner missed its real-time deadline")

    def _update_planner_rate(self, started_ns: int) -> int:
        finished = monotonic_ns()
        if self._last_planner_ns is not None and finished > self._last_planner_ns:
            self._planner_hz = 1_000_000_000.0 / (finished - self._last_planner_ns)
        self._last_planner_ns = finished
        if finished < started_ns:
            raise RuntimeError("planner clock moved backwards")
        return finished

    def _ship_decision(self, snapshot: PerceptionSnapshot) -> ShipDecision:
        player = snapshot.tracked_player
        if player.bounds is None or snapshot.local_geometry is None:
            raise RuntimeError("ship planner lacks player or geometry")
        state = ShipState(
            0.0,
            0.0,
            max(20.0, abs(snapshot.scroll.speed_px_s)),
            -player.vy,
            player.bounds.width,
            player.bounds.height,
            self._controller.held if self._controller is not None else False,
            player.confidence,
        )
        return plan_ship_action(state, snapshot.local_geometry, ShipPhysicsParameters())

    def _fail_closed(self, reason: str) -> None:
        self._last_error = reason
        if self._controller is not None:
            self._controller.fail_closed()
        if self.state.state is AppState.RUNNING:
            self.state.transition(AppState.DEGRADED, reason)

    def _record_run(
        self,
        snapshot: PerceptionSnapshot,
        ended_ns: int,
        outcome: str,
        cause: str | None,
    ) -> None:
        if self._run_history is None or self._attempt_started_ns is None:
            return
        try:
            self._run_history.append(
                RunSummary(
                    self._attempt,
                    self._attempt_started_ns,
                    ended_ns,
                    outcome,
                    snapshot.tracked_player.mode.value,
                    cause,
                    self._planner_confidence,
                    0,
                )
            )
        except (OSError, ValueError) as exc:
            self._last_error = f"run summary could not be saved: {exc}"
