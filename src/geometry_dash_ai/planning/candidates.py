"""Bounded deterministic cube action candidate generation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

HARD_MAX_CANDIDATES = 64
HARD_MAX_JUMP_DELAY_FRAMES = 240


class CubeAction(StrEnum):
    NO_INPUT = "no_input"
    JUMP = "jump"


@dataclass(frozen=True, slots=True)
class CubeActionCandidate:
    action: CubeAction
    jump_delay_frames: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.action, CubeAction):
            raise ValueError("invalid cube action")
        if self.action is CubeAction.NO_INPUT and self.jump_delay_frames is not None:
            raise ValueError("no-input candidate cannot have a jump delay")
        if self.action is CubeAction.JUMP:
            if isinstance(self.jump_delay_frames, bool) or not isinstance(
                self.jump_delay_frames, int
            ):
                raise ValueError("jump candidate requires an integer frame delay")
            if self.jump_delay_frames < 0:
                raise ValueError("jump delay cannot be negative")

    @property
    def label(self) -> str:
        if self.action is CubeAction.NO_INPUT:
            return "NO INPUT"
        assert self.jump_delay_frames is not None
        if self.jump_delay_frames == 0:
            return "JUMP NOW"
        suffix = "FRAME" if self.jump_delay_frames == 1 else "FRAMES"
        return f"JUMP +{self.jump_delay_frames} {suffix}"


def generate_cube_candidates(
    maximum_jump_delay_frames: int,
    delay_increment_frames: int,
    maximum_candidates: int,
) -> tuple[CubeActionCandidate, ...]:
    """Generate no-input and delayed-jump candidates within explicit limits."""
    values = {
        "maximum_jump_delay_frames": maximum_jump_delay_frames,
        "delay_increment_frames": delay_increment_frames,
        "maximum_candidates": maximum_candidates,
    }
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
    if maximum_jump_delay_frames < 3:
        raise ValueError("maximum jump delay must include frames 0 through 3")
    if maximum_jump_delay_frames > HARD_MAX_JUMP_DELAY_FRAMES:
        raise ValueError(
            f"maximum jump delay cannot exceed {HARD_MAX_JUMP_DELAY_FRAMES} frames"
        )
    if delay_increment_frames <= 0:
        raise ValueError("delay increment must be positive")
    if not 5 <= maximum_candidates <= HARD_MAX_CANDIDATES:
        raise ValueError(f"maximum candidates must be in [5, {HARD_MAX_CANDIDATES}]")

    delays = list(range(0, maximum_jump_delay_frames + 1, delay_increment_frames))
    for required in (0, 1, 2, 3):
        if required not in delays:
            delays.append(required)
    delays.sort()
    if len(delays) + 1 > maximum_candidates:
        delays = delays[: maximum_candidates - 1]
    return (CubeActionCandidate(CubeAction.NO_INPUT, None),) + tuple(
        CubeActionCandidate(CubeAction.JUMP, delay) for delay in delays
    )
