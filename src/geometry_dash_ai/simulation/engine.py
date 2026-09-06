"""Fixed-step synthetic Geometry Dash-like simulation."""

from __future__ import annotations

from dataclasses import replace

from geometry_dash_ai.simulation.models import (
    Action,
    Collision,
    GameMode,
    Level,
    PlayerState,
    Rect,
    SimulationConfig,
    SimulationStatus,
    StepResult,
)

_EPSILON = 1e-6


class Simulator:
    """A small deterministic environment with known, configurable physics."""

    def __init__(
        self,
        level: Level,
        config: SimulationConfig | None = None,
        initial_state: PlayerState | None = None,
    ) -> None:
        self.level = level
        self.config = config or SimulationConfig()
        self._initial_state = replace(initial_state) if initial_state else PlayerState()
        self.state = replace(self._initial_state)
        self.status = SimulationStatus.RUNNING
        self.elapsed_seconds = 0.0
        self.camera_x = 0.0
        self._next_portal = 0

    def reset(self) -> StepResult:
        self.state = replace(self._initial_state)
        self.status = SimulationStatus.RUNNING
        self.elapsed_seconds = 0.0
        self.camera_x = 0.0
        self._next_portal = 0
        return self._result()

    def step(self, action: Action = Action.NONE) -> StepResult:
        if self.status is not SimulationStatus.RUNNING:
            raise RuntimeError("reset the simulator before stepping a terminal state")

        previous = replace(self.state)
        self._apply_input(action)
        dt = self.config.step_seconds
        self.state.vx = self.config.horizontal_speed
        self.state.x += self.state.vx * dt

        if self.state.mode is GameMode.CUBE:
            self.state.vy += self.config.cube_gravity * dt
        else:
            acceleration = (
                self.config.ship_up_acceleration
                if self.state.input_held
                else self.config.ship_down_acceleration
            )
            self.state.vy = min(
                self.config.ship_max_up_velocity,
                max(self.config.ship_max_down_velocity, self.state.vy + acceleration * dt),
            )
        self.state.y += self.state.vy * dt

        transitions = self._apply_portals(previous.x, self.state.x)
        collision = self._resolve_or_detect_collision(previous)
        self.elapsed_seconds += dt
        self.camera_x = max(0.0, self.state.x - self.config.player_screen_x)

        if collision is not None:
            self.status = SimulationStatus.DEAD
        elif self.state.x >= self.level.length:
            self.status = SimulationStatus.COMPLETE
        return self._result(collision=collision, transitions=transitions)

    def _apply_input(self, action: Action) -> None:
        if action in {Action.PRESS, Action.HOLD}:
            self.state.input_held = True
        elif action is Action.RELEASE:
            self.state.input_held = False

        if self.state.mode is GameMode.CUBE and self.state.input_held and self.state.grounded:
            self.state.vy = self.config.cube_jump_velocity
            self.state.grounded = False

    def _apply_portals(self, previous_x: float, current_x: float) -> tuple[GameMode, ...]:
        transitions: list[GameMode] = []
        portals = self.level.portals
        while self._next_portal < len(portals):
            portal = portals[self._next_portal]
            if portal.x > current_x:
                break
            if portal.x >= previous_x:
                self.state.mode = portal.mode
                self.state.grounded = False
                self.state.vy = 0.0
                if portal.mode is GameMode.SHIP:
                    self.state.y = max(self.state.y, self.config.player_height * 3.0)
                transitions.append(portal.mode)
            self._next_portal += 1
        return tuple(transitions)

    def _player_rect(self) -> Rect:
        return Rect(
            self.state.x,
            self.state.y,
            self.config.player_width,
            self.config.player_height,
        )

    def _resolve_or_detect_collision(self, previous: PlayerState) -> Collision | None:
        player = self._player_rect()
        if player.top >= self.level.ceiling_y:
            return Collision("ceiling")

        for index, spike in enumerate(self.level.spikes):
            if player.overlaps(spike.bounds):
                return Collision("spike", index)

        for index, block in enumerate(self.level.blocks):
            if not player.overlaps(block.bounds):
                continue
            landed = (
                self.state.vy <= 0
                and previous.y >= block.bounds.top - _EPSILON
                and previous.x + self.config.player_width > block.bounds.x
            )
            if landed and self.state.mode is GameMode.CUBE:
                self.state.y = block.bounds.top
                self.state.vy = 0.0
                self.state.grounded = True
                player = self._player_rect()
                continue
            return Collision("block", index)

        floor_height = self._floor_height(player)
        if floor_height is not None and self.state.y <= floor_height:
            if self.state.mode is GameMode.CUBE and previous.y >= floor_height - _EPSILON:
                self.state.y = floor_height
                self.state.vy = 0.0
                self.state.grounded = True
            else:
                return Collision("floor")
        elif floor_height is None:
            self.state.grounded = False

        if self.state.y + self.config.player_height < -self.config.player_height:
            return Collision("gap")
        return None

    def _floor_height(self, player: Rect) -> float | None:
        heights = [
            segment.height
            for segment in self.level.floor
            if player.right > segment.start_x and player.x < segment.end_x
        ]
        return max(heights) if heights else None

    def _result(
        self,
        collision: Collision | None = None,
        transitions: tuple[GameMode, ...] = (),
    ) -> StepResult:
        return StepResult(
            state=replace(self.state),
            status=self.status,
            elapsed_seconds=self.elapsed_seconds,
            camera_x=self.camera_x,
            collision=collision,
            transitions=transitions,
        )
