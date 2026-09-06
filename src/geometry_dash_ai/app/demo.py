"""Headless pixel-boundary synthetic alpha demo and performance benchmark."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic_ns, perf_counter

from geometry_dash_ai.app.supervisor import RuntimeSupervisor
from geometry_dash_ai.config.settings import AppConfig
from geometry_dash_ai.control import MockActionBackend
from geometry_dash_ai.simulation.engine import Simulator
from geometry_dash_ai.simulation.models import (
    Action,
    FloorSegment,
    GameMode,
    Level,
    ModePortal,
    PlayerState,
    SimulationStatus,
)
from geometry_dash_ai.simulation.render import render_step
from geometry_dash_ai.vision.__main__ import build_pipeline
from geometry_dash_ai.vision.run_state import detect_completion_visual_cue


@dataclass(frozen=True, slots=True)
class DemoResult:
    completed: bool
    frames: int
    transitions: tuple[str, ...]
    input_events: int
    elapsed_ms: float


def run_demo(maximum_frames: int = 360) -> DemoResult:
    """Drive simulation only through rendered pixels and the action abstraction."""
    if not 60 <= maximum_frames <= 2_000:
        raise ValueError("demo frame limit must be within 60..2000")
    level = Level(
        length=420.0,
        floor=(FloorSegment(0.0, 420.0),),
        ceiling_y=220.0,
        portals=(ModePortal(110.0, GameMode.SHIP), ModePortal(290.0, GameMode.CUBE)),
    )
    simulator = Simulator(level, initial_state=PlayerState())
    config = AppConfig()
    pipeline = build_pipeline(config)
    supervisor = RuntimeSupervisor(setup_complete=True)
    supervisor.begin_capture()
    backend = MockActionBackend()
    transitions: list[str] = []
    timestamp = monotonic_ns()
    result = simulator.reset()
    started = perf_counter()
    # Prime perception before requesting synthetic keyboard permission.
    for sequence in range(2):
        frame = render_step(result, level, sequence, timestamp)
        snapshot = pipeline.process(frame)
        if sequence == 0:
            supervisor.capture_ready()
        timestamp += 16_666_667
    supervisor.enter_shadow()
    supervisor.attach_control(backend)
    readiness = supervisor.readiness(snapshot, frame.timestamp_ns + 1_000_000)
    supervisor.arm(frame.timestamp_ns + 1_000_000, readiness)
    supervisor.start(frame.timestamp_ns + 2_000_000)
    last_mode = result.state.mode
    frames = 2
    for sequence in range(2, maximum_frames):
        frame = render_step(result, level, sequence, timestamp)
        snapshot = pipeline.process(frame)
        supervisor.process(
            snapshot,
            timestamp + 1_000_000,
            completion_visual_cue=detect_completion_visual_cue(frame),
        )
        if result.status is SimulationStatus.COMPLETE:
            frames = sequence + 1
            break
        action = Action.HOLD if backend.held else Action.RELEASE
        result = simulator.step(action)
        if result.state.mode is not last_mode:
            transitions.append(f"{last_mode.value}->{result.state.mode.value}")
            last_mode = result.state.mode
        timestamp += 16_666_667
        frames = sequence + 1
        if result.status is SimulationStatus.DEAD:
            break
    completed = result.status is SimulationStatus.COMPLETE
    supervisor.close()
    return DemoResult(
        completed,
        frames,
        tuple(transitions),
        len(backend.events),
        (perf_counter() - started) * 1_000.0,
    )
