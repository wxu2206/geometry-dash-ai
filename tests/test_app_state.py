from __future__ import annotations

import unittest
from random import Random

from geometry_dash_ai.app.state import (
    _TRANSITIONS,
    ApplicationStateMachine,
    AppState,
    InvalidTransition,
)
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

    def test_transition_graph_accepts_declared_edges_and_preserves_rejected_state(self) -> None:
        for source, allowed in _TRANSITIONS.items():
            for target in AppState:
                with self.subTest(source=source, target=target):
                    machine = ApplicationStateMachine()
                    machine._state = source
                    machine._last = machine.last_transition
                    universally_stoppable = target is AppState.STOPPING and source not in {
                        AppState.STOPPING,
                        AppState.STOPPED,
                    }
                    if target in allowed or universally_stoppable:
                        machine.transition(target, "model edge")
                        self.assertIs(machine.state, target)
                    else:
                        with self.assertRaises(InvalidTransition):
                            machine.transition(target, "model edge")
                        self.assertIs(machine.state, source)

    def test_fixed_seed_transition_random_walk_never_mutates_through_rejected_edges(self) -> None:
        randomizer = Random(20260920)
        machine = ApplicationStateMachine()
        for _ in range(2_500):
            if machine.state is AppState.STOPPED:
                machine = ApplicationStateMachine()
            source = machine.state
            target = randomizer.choice(tuple(AppState))
            universally_stoppable = target is AppState.STOPPING and source not in {
                AppState.STOPPING,
                AppState.STOPPED,
            }
            if target in _TRANSITIONS[source] or universally_stoppable:
                machine.transition(target, "seeded model walk")
                self.assertIs(machine.state, target)
            else:
                with self.assertRaises(InvalidTransition):
                    machine.transition(target, "seeded model walk")
                self.assertIs(machine.state, source)


if __name__ == "__main__":
    unittest.main()
