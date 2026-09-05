"""Synthetic world and dynamics data models.

Coordinates use a conventional Cartesian system: x increases to the right and y
increases upward. Player positions refer to the lower-left corner of its collision
box. Geometry is expressed in world coordinates; ``screen_x`` is derived from the
camera offset.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class GameMode(StrEnum):
    CUBE = "cube"
    SHIP = "ship"


class Action(StrEnum):
    NONE = "none"
    PRESS = "press"
    HOLD = "hold"
    RELEASE = "release"


class SimulationStatus(StrEnum):
    RUNNING = "running"
    DEAD = "dead"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def top(self) -> float:
        return self.y + self.height

    def overlaps(self, other: Rect) -> bool:
        return (
            self.x < other.right
            and self.right > other.x
            and self.y < other.top
            and self.top > other.y
        )


@dataclass(frozen=True, slots=True)
class FloorSegment:
    start_x: float
    end_x: float
    height: float = 0.0

    def __post_init__(self) -> None:
        if self.end_x <= self.start_x:
            raise ValueError("floor segment end_x must be greater than start_x")


@dataclass(frozen=True, slots=True)
class Block:
    bounds: Rect


@dataclass(frozen=True, slots=True)
class Spike:
    x: float
    base_y: float
    width: float = 24.0
    height: float = 24.0

    @property
    def bounds(self) -> Rect:
        return Rect(self.x, self.base_y, self.width, self.height)


@dataclass(frozen=True, slots=True)
class ModePortal:
    x: float
    mode: GameMode


@dataclass(frozen=True, slots=True)
class Level:
    length: float
    floor: tuple[FloorSegment, ...]
    ceiling_y: float = 360.0
    blocks: tuple[Block, ...] = ()
    spikes: tuple[Spike, ...] = ()
    portals: tuple[ModePortal, ...] = ()

    def __post_init__(self) -> None:
        if self.length <= 0:
            raise ValueError("level length must be positive")
        if self.ceiling_y <= 0:
            raise ValueError("ceiling_y must be positive")


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    step_seconds: float = 1.0 / 60.0
    horizontal_speed: float = 180.0
    cube_gravity: float = -1300.0
    cube_jump_velocity: float = 480.0
    ship_up_acceleration: float = 760.0
    ship_down_acceleration: float = -620.0
    ship_max_up_velocity: float = 260.0
    ship_max_down_velocity: float = -260.0
    player_width: float = 24.0
    player_height: float = 24.0
    viewport_width: float = 640.0
    player_screen_x: float = 160.0

    def __post_init__(self) -> None:
        if self.step_seconds <= 0:
            raise ValueError("step_seconds must be positive")
        if self.horizontal_speed <= 0:
            raise ValueError("horizontal_speed must be positive")
        if self.player_width <= 0 or self.player_height <= 0:
            raise ValueError("player dimensions must be positive")


@dataclass(slots=True)
class PlayerState:
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    mode: GameMode = GameMode.CUBE
    grounded: bool = True
    input_held: bool = False


@dataclass(frozen=True, slots=True)
class Collision:
    kind: str
    obstacle_index: int | None = None


@dataclass(frozen=True, slots=True)
class StepResult:
    state: PlayerState
    status: SimulationStatus
    elapsed_seconds: float
    camera_x: float
    collision: Collision | None = None
    transitions: tuple[GameMode, ...] = field(default_factory=tuple)

    @property
    def screen_x(self) -> float:
        return self.state.x - self.camera_x
