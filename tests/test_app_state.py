from __future__ import annotations

import unittest

from geometry_dash_ai.app.state import ApplicationStateMachine, AppState, InvalidTransition
from geometry_dash_ai.app.ui_model import buttons_for, prominent_status


class AppStateTests(unittest.TestCase):
    def test_happy_path_is_explicit_and_labels_are_unambiguous(self) -> None:
        machine = ApplicationStateMachine()
        for state in (
            AppState.READY,
            AppState.CAPTURE_CONNECTING,
            AppState.OBSERVING,
            AppState.SHADOW,
            AppState.CONTROL_PERMISSION,
            AppState.ARMED,
            AppState.RUNNING,
        ):
            machine.transition(state, "test transition")
        self.assertEqual(prominent_status(machine.state), "AI CONTROLLING GAME")
        self.assertTrue(buttons_for(machine.state, control_permission=True).pause)

    def test_invalid_transition_is_rejected(self) -> None:
        machine = ApplicationStateMachine()
        with self.assertRaises(InvalidTransition):
            machine.transition(AppState.RUNNING, "skip every safety gate")

    def test_stop_is_available_from_every_active_state(self) -> None:
        for target in (
            AppState.STARTING,
            AppState.READY,
            AppState.OBSERVING,
            AppState.SHADOW,
            AppState.ARMED,
            AppState.RUNNING,
            AppState.PAUSED,
            AppState.DEGRADED,
            AppState.ERROR,
        ):
            machine = ApplicationStateMachine()
            if target is not AppState.STARTING:
                machine._state = target  # Test the universal stop invariant directly.
            machine.stop()
            self.assertIs(machine.state, AppState.STOPPED)


if __name__ == "__main__":
    unittest.main()
