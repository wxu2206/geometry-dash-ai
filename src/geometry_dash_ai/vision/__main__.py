"""Run the Phase 3 observe-only visual pipeline."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from geometry_dash_ai.capture import (
    CaptureRegion,
    CaptureUnavailable,
    MssFrameSource,
    PipeWirePortalFrameSource,
    SyntheticFrameSource,
)
from geometry_dash_ai.capture.source import FrameSource
from geometry_dash_ai.config.settings import AppConfig, load_config
from geometry_dash_ai.telemetry import ShadowTelemetryWriter
from geometry_dash_ai.telemetry.frames import DiagnosticFrameBuffer
from geometry_dash_ai.tracking import GeometryFuser, PlayerTracker, ScrollEstimator
from geometry_dash_ai.ui import DebugViewerUnavailable, TkDebugViewer
from geometry_dash_ai.vision.geometry import ClassicalGeometryDetector, GeometryDetectorConfig
from geometry_dash_ai.vision.pipeline import PerceptionPipeline
from geometry_dash_ai.vision.player import ClassicalPlayerDetector, PlayerDetectorConfig
from geometry_dash_ai.vision.runtime import ObserveOnlyRuntime


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run observe-only Geometry Dash visual perception")
    parser.add_argument("--config", type=Path, default=Path("config/default.toml"))
    parser.add_argument("--local-config", type=Path, default=Path("config/local.toml"))
    parser.add_argument(
        "--frames", type=int, default=120, help="bounded frame count; omit only for manual use"
    )
    parser.add_argument(
        "--preview", action="store_true", help="show a local debug window if Tk is available"
    )
    parser.add_argument(
        "--shadow-log",
        type=Path,
        help="explicit local-only JSONL path relative to data/runs (never stores frames)",
    )
    return parser


def _pipeline(config: AppConfig) -> PerceptionPipeline:
    return PerceptionPipeline(
        ClassicalPlayerDetector(
            PlayerDetectorConfig(
                config.vision.player_min_pixels,
                config.vision.player_max_pixels,
                config.vision.color_tolerance,
                config.vision.cube_color,
                config.vision.ship_color,
            )
        ),
        ClassicalGeometryDetector(GeometryDetectorConfig(config.vision.geometry_min_area_px)),
        PlayerTracker(
            config.vision.maximum_velocity_px_s,
            config.vision.mode_history_frames,
            config.vision.tracker_max_missing_seconds,
        ),
        GeometryFuser(config.vision.geometry_cache_frames),
        ScrollEstimator(),
        config.vision.minimum_confidence,
        config.planning.maximum_obstacles,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = load_config(args.config, args.local_config if args.local_config.exists() else None)
    region = CaptureRegion(
        config.capture.left,
        config.capture.top,
        config.capture.width,
        config.capture.height,
        config.capture.monitor,
    )
    try:
        if config.capture.backend == "synthetic":
            image: Any = np.zeros((region.height, region.width, 3), dtype=np.uint8)
            source: FrameSource
            source = SyntheticFrameSource(region, (image,))
        elif config.capture.backend == "portal":
            source = PipeWirePortalFrameSource(region, config.capture.target_fps)
        else:
            source = MssFrameSource(region, config.capture.target_fps)
    except CaptureUnavailable as exc:
        print(f"capture unavailable: {exc}")
        return 2
    viewer = None
    if args.preview:
        try:
            viewer = TkDebugViewer(preview_scale=config.capture.preview_scale)
        except DebugViewerUnavailable as exc:
            print(f"preview unavailable: {exc}")
    writer = ShadowTelemetryWriter(args.shadow_log) if args.shadow_log is not None else None
    if writer is None:
        metrics, snapshot = _run(source, config, viewer, args.frames, None)
    else:
        with writer:
            metrics, snapshot = _run(source, config, viewer, args.frames, writer.write)
    if snapshot is not None:
        capture_rate = f"{metrics.capture_fps:.2f}"
        print(
            f"observe-only complete: frames={metrics.processed} capture_fps={capture_rate} "
            f"mode={snapshot.tracked_player.mode.value} unreliable={snapshot.perception_unreliable}"
        )
    return 0


def _run(
    source: FrameSource,
    config: AppConfig,
    viewer: TkDebugViewer | None,
    frames: int | None,
    telemetry: Any,
) -> tuple[Any, Any]:
    return ObserveOnlyRuntime(
        source,
        _pipeline(config),
        config.capture.target_fps,
        DiagnosticFrameBuffer(config.recording.maximum_recent_frames)
        if config.recording.enabled
        else None,
        viewer,
        shadow_mode=True,
        telemetry=telemetry,
    ).run(frames)


if __name__ == "__main__":
    raise SystemExit(main())
