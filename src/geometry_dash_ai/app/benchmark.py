"""Non-brittle local performance measurements; never used as CI thresholds."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

import numpy as np

from geometry_dash_ai.capture import CapturedFrame, CaptureRegion
from geometry_dash_ai.physics import (
    CubePhysicsParameters,
    CubeState,
    FloorSegment,
    LocalGeometry,
    ShipState,
    Spike,
)
from geometry_dash_ai.planning import plan_cube_action, plan_ship_action
from geometry_dash_ai.tracking import GeometryFuser, PlayerTracker, ScrollEstimator
from geometry_dash_ai.vision import ClassicalGeometryDetector, ClassicalPlayerDetector
from geometry_dash_ai.vision.pipeline import PerceptionPipeline


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    name: str
    iterations: int
    total_ms: float

    @property
    def rate_hz(self) -> float:
        return 0.0 if self.total_ms <= 0 else self.iterations * 1_000.0 / self.total_ms


def run_benchmarks() -> tuple[BenchmarkResult, ...]:
    image_frame = _benchmark_frame()
    player = ClassicalPlayerDetector()
    geometry_detector = ClassicalGeometryDetector()
    pipeline = PerceptionPipeline(
        ClassicalPlayerDetector(),
        ClassicalGeometryDetector(),
        PlayerTracker(),
        GeometryFuser(),
        ScrollEstimator(),
    )
    local = LocalGeometry(
        floors=(FloorSegment(-100.0, 1_000.0),),
        spikes=(Spike(150.0, 0.0, 24.0, 24.0),),
    )
    cube = CubeState(0.0, 0.0, 180.0, 0.0, 24.0, 24.0, True)
    ship = ShipState(0.0, 80.0, 180.0, 0.0, 24.0, 24.0, False)
    return (
        _measure("player_detection", 100, lambda: player.detect(image_frame)),
        _measure("geometry_detection", 100, lambda: geometry_detector.detect(image_frame, None)),
        _measure(
            "full_perception",
            50,
            lambda: pipeline.process(_next_frame(image_frame)),
        ),
        _measure(
            "cube_planner",
            30,
            lambda: plan_cube_action(cube, local, CubePhysicsParameters()),
        ),
        _measure("ship_planner", 100, lambda: plan_ship_action(ship, local)),
    )


def _measure(name: str, iterations: int, operation: Callable[[], object]) -> BenchmarkResult:
    started = perf_counter()
    for _ in range(iterations):
        operation()
    return BenchmarkResult(name, iterations, (perf_counter() - started) * 1_000.0)


_SEQUENCE = 0


def _next_frame(template: CapturedFrame) -> CapturedFrame:
    global _SEQUENCE
    _SEQUENCE += 1
    return CapturedFrame(
        template.image,
        1_000_000_000 + _SEQUENCE * 16_666_667,
        _SEQUENCE,
        template.region,
    )


def _benchmark_frame() -> CapturedFrame:
    image = np.full((180, 320, 3), (18, 24, 40), dtype=np.uint8)
    image[140:145, :] = (210, 210, 210)
    image[116:140, 52:72] = (255, 60, 200)
    image[92:140, 220:256] = (220, 220, 220)
    for offset in range(24):
        half_width = max(1, (offset + 1) // 2)
        image[139 - offset, 172 - half_width : 172 + half_width] = (250, 45, 35)
    return CapturedFrame(image, 1_000_000_000, 0, CaptureRegion(0, 0, 320, 180))
