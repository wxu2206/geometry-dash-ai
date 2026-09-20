"""Reusable deterministic synthetic scenario catalog for offline reliability tests.

These compact mechanics-focused scenes are intentionally not Stereo Madness
data. They provide stable combinations of floor, gaps, hazards, platforms, and
mode portals at the normal rendered-pixel boundary.
"""

from __future__ import annotations

from dataclasses import dataclass

from geometry_dash_ai.simulation.models import (
    Block,
    FloorSegment,
    GameMode,
    Level,
    ModePortal,
    PlayerState,
    Rect,
    Spike,
)


@dataclass(frozen=True, slots=True)
class SyntheticScenario:
    """One bounded, inspectable synthetic mechanics situation."""

    name: str
    level: Level
    initial_state: PlayerState
    expect_spike: bool = False
    expect_gap: bool = False
    transitions: tuple[GameMode, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("_", "").isalnum():
            raise ValueError("synthetic scenario name is invalid")
        if not isinstance(self.level, Level) or not isinstance(self.initial_state, PlayerState):
            raise ValueError("synthetic scenario has invalid world state")
        if not all(isinstance(mode, GameMode) for mode in self.transitions):
            raise ValueError("synthetic scenario transitions are invalid")


def scenario_catalog() -> tuple[SyntheticScenario, ...]:
    """Return deterministic, reusable representative mechanics scenarios."""
    floor = (FloorSegment(0.0, 1_200.0),)
    return (
        SyntheticScenario("flat", Level(600.0, floor), PlayerState(x=64.0)),
        SyntheticScenario(
            "single_spike",
            Level(600.0, floor, spikes=(Spike(220.0, 0.0),)),
            PlayerState(x=64.0),
            expect_spike=True,
        ),
        SyntheticScenario(
            "triple_spike",
            Level(
                700.0,
                floor,
                spikes=(Spike(220.0, 0.0), Spike(244.0, 0.0), Spike(268.0, 0.0)),
            ),
            PlayerState(x=64.0),
            expect_spike=True,
        ),
        SyntheticScenario(
            "gap",
            Level(700.0, (FloorSegment(0.0, 180.0), FloorSegment(280.0, 700.0))),
            PlayerState(x=64.0),
            expect_gap=True,
        ),
        SyntheticScenario(
            "raised_platform",
            Level(700.0, floor, blocks=(Block(Rect(260.0, 0.0, 120.0, 48.0)),)),
            PlayerState(x=64.0),
        ),
        SyntheticScenario(
            "low_ship_corridor",
            Level(
                700.0,
                floor,
                ceiling_y=96.0,
                blocks=(Block(Rect(240.0, 96.0, 180.0, 16.0)),),
            ),
            PlayerState(x=64.0, y=48.0, grounded=False, mode=GameMode.SHIP),
        ),
        SyntheticScenario(
            "cube_ship_cube",
            Level(
                900.0,
                floor,
                portals=(ModePortal(220.0, GameMode.SHIP), ModePortal(300.0, GameMode.CUBE)),
            ),
            PlayerState(x=64.0),
            transitions=(GameMode.SHIP, GameMode.CUBE),
        ),
    )
