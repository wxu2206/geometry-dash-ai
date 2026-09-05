"""Small synthetic layouts used by examples and tests."""

from geometry_dash_ai.simulation.models import (
    Block,
    FloorSegment,
    GameMode,
    Level,
    ModePortal,
    Rect,
    Spike,
)


def demo_level() -> Level:
    """Return a compact layout exercising obstacles, gaps, and a ship portal."""
    return Level(
        length=1_400.0,
        ceiling_y=300.0,
        floor=(
            FloorSegment(0.0, 620.0),
            FloorSegment(700.0, 1_400.0),
        ),
        blocks=(
            Block(Rect(390.0, 0.0, 72.0, 48.0)),
            Block(Rect(940.0, 0.0, 48.0, 72.0)),
        ),
        spikes=(
            Spike(210.0, 0.0),
            Spike(235.0, 0.0),
            Spike(760.0, 0.0),
        ),
        portals=(ModePortal(720.0, GameMode.SHIP),),
    )
