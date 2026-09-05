"""Typed, confidence-bearing screen-space perception models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


def _finite(name: str, value: object, minimum: float = -1_000_000.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite")
    converted = float(value)
    if not isfinite(converted) or converted < minimum or converted > 1_000_000.0:
        raise ValueError(f"{name} is outside supported bounds")
    return converted


class PlayerMode(StrEnum):
    CUBE = "cube"
    SHIP = "ship"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ScreenBox:
    """A screen-space rectangle with top-left origin and positive y down."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        _finite("ScreenBox.x", self.x)
        _finite("ScreenBox.y", self.y)
        _finite("ScreenBox.width", self.width, 0.0)
        _finite("ScreenBox.height", self.height, 0.0)
        if self.width <= 0 or self.height <= 0:
            raise ValueError("screen box dimensions must be positive")

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2.0, self.y + self.height / 2.0)


@dataclass(frozen=True, slots=True)
class PlayerDetection:
    bounds: ScreenBox
    mode: PlayerMode
    confidence: float
    frame_index: int
    timestamp_ns: int

    def __post_init__(self) -> None:
        if not isinstance(self.bounds, ScreenBox) or not isinstance(self.mode, PlayerMode):
            raise ValueError("player detection has invalid bounds or mode")
        _finite("PlayerDetection.confidence", self.confidence, 0.0)
        if self.confidence > 1.0:
            raise ValueError("player confidence must be in [0, 1]")
        if (
            isinstance(self.frame_index, bool)
            or not isinstance(self.frame_index, int)
            or self.frame_index < 0
        ):
            raise ValueError("player frame index must be non-negative")
        if (
            isinstance(self.timestamp_ns, bool)
            or not isinstance(self.timestamp_ns, int)
            or self.timestamp_ns < 0
        ):
            raise ValueError("player timestamp must be non-negative")


@dataclass(frozen=True, slots=True)
class GeometryDetection:
    """Screen-space geometry where every element carries a conservative confidence."""

    floors: tuple[ScreenBox, ...] = ()
    solids: tuple[ScreenBox, ...] = ()
    spikes: tuple[ScreenBox, ...] = ()
    ceiling: ScreenBox | None = None
    confidence: float = 0.0

    def __post_init__(self) -> None:
        for name in ("floors", "solids", "spikes"):
            items = getattr(self, name)
            if not isinstance(items, tuple) or len(items) > 256:
                raise ValueError(f"geometry {name} must be a bounded tuple")
            if any(not isinstance(item, ScreenBox) for item in items):
                raise ValueError(f"geometry {name} contains an invalid screen box")
        if self.ceiling is not None and not isinstance(self.ceiling, ScreenBox):
            raise ValueError("geometry ceiling is invalid")
        _finite("GeometryDetection.confidence", self.confidence, 0.0)
        if self.confidence > 1.0:
            raise ValueError("geometry confidence must be in [0, 1]")
