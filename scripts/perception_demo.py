"""Run a bounded, observe-only perception smoke test without desktop capture."""

from __future__ import annotations

import argparse

import numpy as np

from geometry_dash_ai.capture import CaptureRegion, SyntheticFrameSource
from geometry_dash_ai.tracking import GeometryFuser, PlayerTracker, ScrollEstimator
from geometry_dash_ai.vision import ClassicalGeometryDetector, ClassicalPlayerDetector
from geometry_dash_ai.vision.pipeline import PerceptionPipeline
from geometry_dash_ai.vision.runtime import ObserveOnlyRuntime


def _frame() -> object:
    image = np.full((180, 320, 3), (18, 24, 40), dtype=np.uint8)
    image[140:145, :130] = (210, 210, 210)
    image[140:145, 190:] = (210, 210, 210)
    image[92:140, 220:256] = (220, 220, 220)
    image[116:140, 52:72] = (255, 60, 200)
    for offset in range(24):
        half = max(1, round((offset + 1) * 24 / 48))
        image[140 - offset - 1, 172 - half : 172 + half] = (250, 45, 35)
    return image


def main() -> int:
    parser = argparse.ArgumentParser(description="Run synthetic observe-only perception")
    parser.add_argument("--frames", type=int, default=120)
    args = parser.parse_args()
    if args.frames <= 0 or args.frames > 2_000:
        raise SystemExit("--frames must be within 1..2000")
    image = _frame()
    source = SyntheticFrameSource(CaptureRegion(0, 0, 320, 180), (image,))
    pipeline = PerceptionPipeline(
        ClassicalPlayerDetector(),
        ClassicalGeometryDetector(),
        PlayerTracker(),
        GeometryFuser(),
        ScrollEstimator(),
    )
    metrics, snapshot = ObserveOnlyRuntime(source, pipeline, 240.0).run(args.frames)
    assert snapshot is not None
    print(
        f"frames={metrics.processed} mode={snapshot.tracked_player.mode.value} "
        f"player_confidence={snapshot.tracked_player.confidence:.2f} "
        f"geometry_items={snapshot.local_geometry.item_count if snapshot.local_geometry else 0} "
        f"latency_ms={snapshot.metrics.processing_latency_ms:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
