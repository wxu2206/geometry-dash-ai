from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from geometry_dash_ai.capture import CapturedFrame, CaptureRegion, SyntheticFrameSource
from geometry_dash_ai.telemetry import DiagnosticFrameBuffer
from geometry_dash_ai.tracking import GeometryFuser, PlayerTracker, ScrollEstimator
from geometry_dash_ai.ui import render_debug_overlay, scale_preview
from geometry_dash_ai.vision import ClassicalGeometryDetector, ClassicalPlayerDetector
from geometry_dash_ai.vision.pipeline import PerceptionPipeline
from geometry_dash_ai.vision.runtime import OBSERVE_ONLY, ObserveOnlyRuntime
from geometry_dash_ai.vision.shadow import (
    ShadowOutcomeComparator,
    evaluate_shadow_plan,
    shadow_payload,
)
from tests.visual_fixtures import frame, scene


class ObserveOnlyTests(unittest.TestCase):
    def test_runtime_has_no_input_dependency_and_processes_synthetic_frames(self) -> None:
        self.assertTrue(OBSERVE_ONLY)
        image = scene()
        source = SyntheticFrameSource(CaptureRegion(0, 0, image.shape[1], image.shape[0]), (image,))
        pipeline = PerceptionPipeline(
            ClassicalPlayerDetector(),
            ClassicalGeometryDetector(),
            PlayerTracker(),
            GeometryFuser(),
            ScrollEstimator(),
        )
        metrics, snapshot = ObserveOnlyRuntime(source, pipeline, 240.0).run(2)
        self.assertEqual(metrics.processed, 2)
        self.assertIsNotNone(snapshot)

    def test_overlay_and_diagnostic_buffer_are_bounded(self) -> None:
        current = frame(scene())
        pipeline = PerceptionPipeline(
            ClassicalPlayerDetector(),
            ClassicalGeometryDetector(),
            PlayerTracker(),
            GeometryFuser(),
            ScrollEstimator(),
        )
        snapshot = pipeline.process(current)
        overlay = render_debug_overlay(
            current.image, snapshot.tracked_player.bounds, snapshot.fused_geometry
        )
        self.assertEqual(overlay.shape, current.image.shape)
        self.assertFalse(np.array_equal(overlay, current.image))
        self.assertEqual(scale_preview(overlay, 0.5).shape, (90, 160, 3))
        with self.assertRaisesRegex(ValueError, "viewer budget"):
            scale_preview(np.zeros((1_025, 1_025, 3), dtype=np.uint8), 3.0)
        buffer = DiagnosticFrameBuffer(2)
        for index in range(3):
            buffer.append(frame(scene(), sequence=index, timestamp_ns=index + 1))
        self.assertEqual(len(buffer.recent()), 2)

    def test_shadow_plan_is_display_only_and_telemetry_never_contains_pixels(self) -> None:
        current = frame(scene())
        snapshot = PerceptionPipeline(
            ClassicalPlayerDetector(),
            ClassicalGeometryDetector(),
            PlayerTracker(),
            GeometryFuser(),
            ScrollEstimator(),
        ).process(current)
        shadow = evaluate_shadow_plan(snapshot)
        self.assertIsNotNone(shadow.decision)
        payload = shadow_payload(snapshot, shadow)
        self.assertIn("recommendation", payload)
        self.assertNotIn("image", str(payload))

    def test_shadow_comparison_inferrs_only_visual_outcome(self) -> None:
        pipeline = PerceptionPipeline(
            ClassicalPlayerDetector(),
            ClassicalGeometryDetector(),
            PlayerTracker(),
            GeometryFuser(),
            ScrollEstimator(),
        )
        first = pipeline.process(frame(scene(), sequence=0, timestamp_ns=1_000_000_000))
        comparator = ShadowOutcomeComparator()
        comparator.record(evaluate_shadow_plan(first))
        later = pipeline.process(frame(scene(), sequence=1, timestamp_ns=3_000_000_000))
        outcomes = comparator.observe(later)
        self.assertEqual(len(outcomes), 1)
        self.assertTrue(outcomes[0].visually_survived_horizon)

    def test_diagnostic_writer_rejects_an_unrelated_root(self) -> None:
        region = CaptureRegion(0, 0, 4, 4)
        buffer = DiagnosticFrameBuffer(1)
        buffer.append(CapturedFrame(np.zeros((4, 4, 3), dtype=np.uint8), 1, 0, region))
        with TemporaryDirectory() as directory, self.assertRaisesRegex(
            ValueError, "active project root"
        ):
            buffer.write_event("death", Path(directory))

    def test_runtime_source_does_not_import_control_package(self) -> None:
        from geometry_dash_ai.vision import runtime

        source = runtime.__file__
        assert source is not None
        with open(source, encoding="utf-8") as stream:
            self.assertNotIn("geometry_dash_ai.control", stream.read())
