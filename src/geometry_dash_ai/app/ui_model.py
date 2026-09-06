"""Headless UI policy model for button availability and safety labels."""

from __future__ import annotations

from dataclasses import dataclass

from geometry_dash_ai.app.state import AppState


@dataclass(frozen=True, slots=True)
class ButtonState:
    setup: bool
    reset: bool
    diagnostics: bool
    observe: bool
    shadow: bool
    request_control: bool
    arm: bool
    start: bool
    pause: bool
    resume: bool
    emergency_stop: bool


def buttons_for(state: AppState, *, control_permission: bool) -> ButtonState:
    active = state not in {AppState.STOPPING, AppState.STOPPED}
    return ButtonState(
        setup=state in {AppState.SETUP_REQUIRED, AppState.READY, AppState.ERROR},
        reset=state in {AppState.SETUP_REQUIRED, AppState.READY, AppState.ERROR},
        diagnostics=active,
        observe=state in {AppState.READY, AppState.DEGRADED},
        shadow=state is AppState.OBSERVING,
        request_control=state is AppState.SHADOW and not control_permission,
        arm=state is AppState.SHADOW and control_permission,
        start=state is AppState.ARMED,
        pause=state is AppState.RUNNING,
        resume=state is AppState.PAUSED,
        emergency_stop=active,
    )


def prominent_status(state: AppState) -> str:
    if state is AppState.ARMED:
        return "LIVE CONTROL ARMED"
    if state is AppState.RUNNING:
        return "AI CONTROLLING GAME"
    if state is AppState.SHADOW:
        return "SHADOW MODE — NO INPUT"
    if state is AppState.OBSERVING:
        return "OBSERVE MODE — NO INPUT"
    return state.value.replace("_", " ").upper()
