"""Command-line demonstration for the synthetic simulator."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from geometry_dash_ai.simulation.engine import Simulator
from geometry_dash_ai.simulation.layouts import demo_level
from geometry_dash_ai.simulation.models import Action, GameMode, SimulationStatus


def _demo_action(simulator: Simulator) -> Action:
    """Use visible synthetic geometry for a simple smoke-test policy."""
    state = simulator.state
    if state.mode is GameMode.SHIP:
        return Action.HOLD if state.y < simulator.level.ceiling_y * 0.45 else Action.RELEASE
    if state.input_held:
        return Action.RELEASE

    lookahead_start = state.x + simulator.config.player_width
    lookahead_end = lookahead_start + 25.0
    spike_ahead = any(
        lookahead_start <= spike.x <= lookahead_end for spike in simulator.level.spikes
    )
    block_ahead = any(
        lookahead_start <= block.bounds.x <= lookahead_end for block in simulator.level.blocks
    )
    floor_ahead = any(
        segment.start_x <= lookahead_end <= segment.end_x for segment in simulator.level.floor
    )
    if state.grounded and (spike_ahead or block_ahead or not floor_ahead):
        return Action.PRESS
    return Action.NONE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the synthetic Geometry Dash environment")
    parser.add_argument("--steps", type=int, default=240, help="maximum fixed steps to simulate")
    parser.add_argument("--report-every", type=int, default=30, help="state reporting interval")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.steps <= 0 or args.report_every <= 0:
        raise SystemExit("--steps and --report-every must be positive")

    simulator = Simulator(demo_level())
    result = simulator.reset()
    for step in range(args.steps):
        result = simulator.step(_demo_action(simulator))
        if step % args.report_every == 0 or result.status is not SimulationStatus.RUNNING:
            print(
                f"step={step:04d} status={result.status.value:<8} "
                f"mode={result.state.mode.value:<4} x={result.state.x:7.1f} "
                f"screen_x={result.screen_x:6.1f} y={result.state.y:6.1f} "
                f"vy={result.state.vy:7.1f}"
            )
        if result.status is not SimulationStatus.RUNNING:
            break
    return 0 if result.status is not SimulationStatus.DEAD else 1


if __name__ == "__main__":
    raise SystemExit(main())
