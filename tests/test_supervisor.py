from __future__ import annotations

import unittest
from dataclasses import replace

from geometry_dash_ai.app.models import Readiness
from geometry_dash_ai.app.state import AppState
from geometry_dash_ai.app.supervisor import RuntimeSupervisor, SupervisorLimits
from geometry_dash_ai.config.settings import AppConfig
from geometry_dash_ai.control import MockActionBackend
from geometry_dash_ai.vision import PlayerMode
from geometry_dash_ai.vision.__main__ import build_pipeline
from tests.visual_fixtures import frame, scene


def _ready() -> Readiness:
    return Readiness(True, True, True, True, True, True, True, True, True, True)


class SupervisorTests(unittest.TestCase):
    def _shadow(self) -> RuntimeSupervisor:
        supervisor = RuntimeSupervisor(setup_complete=True)
        supervisor.begin_capture()
        supervisor.capture_ready()
        supervisor.enter_shadow()
        return supervisor

    def test_observe_shadow_permission_and_arm_send_no_input(self) -> None:
        supervisor = RuntimeSupervisor(setup_complete=True)
        backend = MockActionBackend()
        supervisor.begin_capture()
        supervisor.capture_ready()
        self.assertEqual(backend.events, [])
        supervisor.enter_shadow()
        self.assertEqual(backend.events, [])
        supervisor.attach_control(backend)
        self.assertEqual(backend.events, [])
        supervisor.arm(1_000_000_000, _ready())
        self.assertEqual(backend.events, [])
        supervisor.pause()
        self.assertEqual(backend.events, [])

    def test_denied_permission_stays_in_shadow(self) -> None:
        supervisor = self._shadow()
        backend = MockActionBackend(granted=False)
        with self.assertRaisesRegex(RuntimeError, "not granted"):
            supervisor.attach_control(backend)
        self.assertIs(supervisor.state.state, AppState.SHADOW)
        self.assertEqual(backend.events, [])

    def test_ship_shadow_plans_without_input_backend(self) -> None:
        pipeline = build_pipeline(AppConfig())
        snapshot = None
        for sequence in range(6):
            snapshot = pipeline.process(
                frame(
                    scene(mode=PlayerMode.SHIP),
                    sequence,
                    2_000_000_000 + sequence * 16_666_667,
                )
            )
        assert snapshot is not None
        supervisor = self._shadow()
        supervisor.plan_shadow(snapshot)
        self.assertIsNotNone(supervisor.ship_shadow)
        self.assertIsNone(supervisor.cube_shadow)
        self.assertIs(supervisor.state.state, AppState.SHADOW)

    def test_capture_staleness_and_unknown_mode_release_input(self) -> None:
        pipeline = build_pipeline(AppConfig())
        snapshot = None
        for sequence in range(6):
            snapshot = pipeline.process(
                frame(
                    scene(),
                    sequence=sequence,
                    timestamp_ns=1_000_000_000 + sequence * 16_666_667,
                )
            )
        assert snapshot is not None
        supervisor = self._shadow()
        backend = MockActionBackend()
        supervisor.process(snapshot, snapshot.frame.timestamp_ns + 1_000_000)
        supervisor.attach_control(backend)
        supervisor.arm(snapshot.frame.timestamp_ns + 2_000_000, _ready())
        supervisor.start(snapshot.frame.timestamp_ns + 3_000_000)
        controller = supervisor.controller
        assert controller is not None
        controller.set_held(
            True,
            snapshot.frame.timestamp_ns + 4_000_000,
            snapshot.frame.timestamp_ns + 20_000_000,
        )
        supervisor.process(snapshot, snapshot.frame.timestamp_ns + 200_000_000)
        self.assertIs(supervisor.state.state, AppState.DEGRADED)
        self.assertFalse(backend.held)

        second = self._shadow()
        second_backend = MockActionBackend()
        second.process(snapshot, snapshot.frame.timestamp_ns + 1_000_000)
        second.attach_control(second_backend)
        second.arm(snapshot.frame.timestamp_ns + 2_000_000, _ready())
        second.start(snapshot.frame.timestamp_ns + 3_000_000)
        unknown_player = replace(snapshot.tracked_player, mode=PlayerMode.UNKNOWN)
        unknown = replace(snapshot, tracked_player=unknown_player)
        second.process(unknown, snapshot.frame.timestamp_ns + 4_000_000)
        self.assertIs(second.state.state, AppState.DEGRADED)
        self.assertFalse(second_backend.held)

    def test_emergency_stop_and_attempt_limit_are_fail_closed(self) -> None:
        supervisor = self._shadow()
        backend = MockActionBackend()
        supervisor.attach_control(backend)
        supervisor.arm(1_000_000_000, _ready())
        supervisor.start(1_000_000_001)
        controller = supervisor.controller
        assert controller is not None
        controller.set_held(True, 1_000_000_002, 1_100_000_000)
        supervisor.emergency_stop()
        self.assertIs(supervisor.state.state, AppState.STOPPED)
        self.assertFalse(backend.held)
        self.assertTrue(backend.closed)

        limited = RuntimeSupervisor(
            setup_complete=True,
            limits=SupervisorLimits(maximum_attempts=1),
        )
        limited.begin_capture()
        limited.capture_ready()
        limited.enter_shadow()
        limited.attach_control(MockActionBackend())
        limited.arm(2_000_000_000, _ready())
        limited.start(2_000_000_001)
        limited.state.transition(AppState.DEAD, "visually confirmed test death")
        with self.assertRaisesRegex(RuntimeError, "attempt limit"):
            limited.retry(4_000_000_000)
        self.assertIs(limited.state.state, AppState.SHADOW)
        assert limited.controller is not None
        self.assertFalse(limited.controller.armed)

    def test_planner_error_releases_and_degrades(self) -> None:
        pipeline = build_pipeline(AppConfig())
        snapshot = None
        for sequence in range(6):
            snapshot = pipeline.process(
                frame(scene(), sequence, 3_000_000_000 + sequence * 16_666_667)
            )
        assert snapshot is not None
        supervisor = self._shadow()
        backend = MockActionBackend()
        supervisor.process(snapshot, snapshot.frame.timestamp_ns + 1_000_000)
        supervisor.attach_control(backend)
        supervisor.arm(snapshot.frame.timestamp_ns + 2_000_000, _ready())
        supervisor.start(snapshot.frame.timestamp_ns + 3_000_000)
        controller = supervisor.controller
        assert controller is not None
        controller.set_held(
            True,
            snapshot.frame.timestamp_ns + 4_000_000,
            snapshot.frame.timestamp_ns + 20_000_000,
        )
        invalid_for_planner = replace(snapshot, local_geometry=None)
        supervisor.process(invalid_for_planner, snapshot.frame.timestamp_ns + 5_000_000)
        self.assertIs(supervisor.state.state, AppState.DEGRADED)
        self.assertFalse(backend.held)

    def test_retry_waits_for_two_visible_reset_frames(self) -> None:
        supervisor = self._shadow()
        backend = MockActionBackend()
        supervisor.attach_control(backend)
        supervisor.arm(1_000_000_000, _ready())
        supervisor.start(1_000_000_001)
        controller = supervisor.controller
        assert controller is not None
        controller.pause()
        supervisor.state.transition(AppState.DEAD, "visual death test")
        supervisor._last_death_ns = 1_000_000_000
        supervisor.retry(3_000_000_000)
        self.assertIs(supervisor.state.state, AppState.RETRYING)
        pipeline = build_pipeline(AppConfig())
        first = pipeline.process(frame(scene(), 0, 3_100_000_000))
        supervisor.process(first, 3_101_000_000)
        self.assertIs(supervisor.state.state, AppState.RETRYING)
        second = pipeline.process(frame(scene(), 1, 3_116_666_667))
        supervisor.process(second, 3_117_000_000)
        self.assertIs(supervisor.state.state, AppState.RUNNING)
        self.assertFalse(backend.held)


if __name__ == "__main__":
    unittest.main()
