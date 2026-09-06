from __future__ import annotations

import unittest

from geometry_dash_ai.control import (
    ControlLimits,
    ControlSafetyError,
    GuardedActionController,
    MockActionBackend,
)


class ControlSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = MockActionBackend()
        self.limits = ControlLimits(
            tap_duration_ms=10.0,
            maximum_hold_ms=50.0,
            maximum_actions_per_second=4,
            heartbeat_timeout_ms=50.0,
            maximum_session_seconds=30.0,
            arming_timeout_seconds=3.0,
        )
        self.controller = GuardedActionController(
            self.backend,
            self.limits,
        )

    def test_permission_and_arming_alone_cannot_send_input(self) -> None:
        self.assertEqual(self.backend.events, [])
        self.controller.arm(1_000_000_000)
        self.assertEqual(self.backend.events, [])
        with self.assertRaisesRegex(ControlSafetyError, "not running"):
            self.controller.tap(1_000_000_001, 1_100_000_000)
        self.assertEqual(self.backend.events, [])

    def test_tap_releases_and_pause_shutdown_release(self) -> None:
        self.controller.arm(1_000_000_000)
        self.controller.start(1_000_000_001)
        self.controller.tap(1_000_000_002, 1_100_000_000)
        self.assertTrue(self.backend.held)
        self.controller.tick(1_011_000_002)
        self.assertEqual(self.backend.events, ["press", "release"])
        self.controller.set_held(True, 1_020_000_000, 1_100_000_000)
        self.controller.pause()
        self.assertFalse(self.backend.held)
        self.controller.start(1_021_000_000)
        self.controller.set_held(True, 1_022_000_000, 1_100_000_000)
        self.controller.close()
        self.assertFalse(self.backend.held)
        self.assertTrue(self.backend.closed)

    def test_stale_decision_permission_loss_and_watchdogs_fail_closed(self) -> None:
        self.controller.arm(1_000_000_000)
        self.controller.start(1_000_000_001)
        with self.assertRaisesRegex(ControlSafetyError, "stale"):
            self.controller.tap(1_100_000_000, 1_099_999_999)
        self.assertFalse(self.controller.armed)

        for failure in ("permission", "hold", "heartbeat"):
            backend = MockActionBackend()
            controller = GuardedActionController(backend, self.limits)
            controller.arm(2_000_000_000)
            controller.start(2_000_000_001)
            if failure == "permission":
                controller.set_held(True, 2_000_000_002, 2_500_000_000)
                backend.revoke()
                with self.assertRaisesRegex(ControlSafetyError, "permission"):
                    controller.set_held(False, 2_010_000_000, 2_500_000_000)
            elif failure == "hold":
                controller.set_held(True, 2_000_000_002, 2_500_000_000)
                with self.assertRaisesRegex(ControlSafetyError, "maximum action hold"):
                    controller.tick(2_051_000_003)
            else:
                with self.assertRaisesRegex(ControlSafetyError, "heartbeat"):
                    controller.tick(2_051_000_003)
            self.assertFalse(backend.held)
            self.assertFalse(controller.running)
            self.assertFalse(controller.armed)

    def test_arming_and_session_expire(self) -> None:
        self.controller.arm(1_000_000_000)
        with self.assertRaisesRegex(ControlSafetyError, "arming expired"):
            self.controller.start(4_000_000_001)
        self.controller.arm(5_000_000_000)
        self.controller.start(5_000_000_001)
        self.controller.heartbeat(35_000_000_002)
        with self.assertRaisesRegex(ControlSafetyError, "session expired"):
            self.controller.tick(35_000_000_002)

    def test_pause_resume_does_not_reset_session_limit_or_reapply_arm_timeout(self) -> None:
        self.controller.arm(1_000_000_000)
        self.controller.start(1_000_000_001)
        self.controller.pause()
        self.controller.start(20_000_000_000)
        self.controller.heartbeat(31_000_000_002)
        with self.assertRaisesRegex(ControlSafetyError, "session expired"):
            self.controller.tick(31_000_000_002)

    def test_release_transport_failure_closes_permission_session(self) -> None:
        class ReleaseFailureBackend(MockActionBackend):
            def release_action(self) -> None:
                raise RuntimeError("release transport failed")

            def close(self) -> None:
                self.held = False
                self.closed = True

        backend = ReleaseFailureBackend()
        controller = GuardedActionController(backend, self.limits)
        controller.arm(1_000_000_000)
        controller.start(1_000_000_001)
        controller.set_held(True, 1_000_000_002, 1_100_000_000)
        with self.assertRaisesRegex(RuntimeError, "release transport"):
            controller.pause()
        self.assertFalse(controller.held)
        self.assertFalse(controller.running)
        self.assertFalse(controller.armed)
        self.assertTrue(backend.closed)


if __name__ == "__main__":
    unittest.main()
