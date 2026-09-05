"""Small, non-brittle local throughput benchmark for the synthetic cube planner."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from time import perf_counter

from geometry_dash_ai.physics import (
    CubePhysicsParameters,
    CubeState,
    FloorSegment,
    LocalGeometry,
    Spike,
)
from geometry_dash_ai.planning import plan_cube_action


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=20)
    args = parser.parse_args(argv)
    if not 1 <= args.iterations <= 100:
        raise SystemExit("--iterations must be in [1, 100]")

    state = CubeState(0.0, 0.0, 180.0, 0.0, 24.0, 24.0, True)
    geometry = LocalGeometry(
        floors=(FloorSegment(-100.0, 1_000.0),),
        spikes=(
            Spike(150.0, 0.0, 24.0, 24.0, "one"),
            Spike(174.0, 0.0, 24.0, 24.0, "two"),
        ),
    )
    physics = CubePhysicsParameters()
    started = perf_counter()
    for _ in range(args.iterations):
        plan_cube_action(state, geometry, physics)
    elapsed = perf_counter() - started
    elapsed = max(elapsed, 1e-12)
    print(
        f"plans={args.iterations} elapsed_seconds={elapsed:.6f} "
        f"plans_per_second={args.iterations / elapsed:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
