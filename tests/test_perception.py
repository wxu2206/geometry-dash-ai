from __future__ import annotations

import unittest

from geometry_dash_ai.tracking import GeometryFuser, PlayerTracker, ScrollEstimator
from geometry_dash_ai.vision import (
    ClassicalGeometryDetector,
    ClassicalPlayerDetector,
    PlayerMode,
)
from geometry_dash_ai.vision.coordinates import CoordinateTransform, local_geometry_from_screen
from geometry_dash_ai.vision.pipeline import PerceptionPipeline
from geometry_dash_ai.vision.planner_preview import preview_cube_plan
from tests.visual_fixtures import FLOOR_Y, frame, scene


class PerceptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.player_detector = ClassicalPlayerDetector()
        self.geometry_detector = ClassicalGeometryDetector()

    def test_cube_and_ship_detection(self) -> None:
        cube = self.player_detector.detect(frame(scene()))
        ship = self.player_detector.detect(frame(scene(mode=PlayerMode.SHIP)))
        self.assertIsNotNone(cube)
        self.assertIsNotNone(ship)
        assert cube is not None and ship is not None
        self.assertIs(cube.mode, PlayerMode.CUBE)
        self.assertIs(ship.mode, PlayerMode.SHIP)
        self.assertGreater(cube.confidence, 0.5)

    def test_floor_spike_gap_and_block_detection(self) -> None:
        detected = self.geometry_detector.detect(frame(scene(noise=True)), None)
        self.assertGreaterEqual(len(detected.floors), 2)
        self.assertGreaterEqual(len(detected.spikes), 1)
        self.assertGreaterEqual(len(detected.solids), 1)
        gap_left = detected.floors[0].right
        gap_right = detected.floors[1].x
        self.assertGreater(gap_right, gap_left)

    def test_coordinate_transform_uses_player_relative_y_up(self) -> None:
        detected_player = self.player_detector.detect(frame(scene()))
        assert detected_player is not None
        transform = CoordinateTransform(detected_player.bounds)
        x, y = transform.point(detected_player.bounds.x, detected_player.bounds.bottom)
        self.assertEqual((x, y), (0.0, 0.0))
        self.assertGreater(transform.point(100, FLOOR_Y)[1], -1.0)

    def test_pipeline_converts_geometry_and_flags_missing_player(self) -> None:
        pipeline = PerceptionPipeline(
            self.player_detector,
            self.geometry_detector,
            PlayerTracker(),
            GeometryFuser(),
            ScrollEstimator(),
        )
        snapshot = pipeline.process(frame(scene()))
        self.assertIsNotNone(snapshot.local_geometry)
        assert snapshot.local_geometry is not None
        self.assertGreaterEqual(len(snapshot.local_geometry.spikes), 1)
        self.assertIsNotNone(preview_cube_plan(snapshot))
        missing_frame = frame(scene(include_player=False), sequence=1, timestamp_ns=1_016_000_000)
        missing = pipeline.process(missing_frame)
        self.assertFalse(missing.perception_unreliable)
        eventual_missing = pipeline.process(
            frame(scene(include_player=False), sequence=2, timestamp_ns=2_000_000_000)
        )
        self.assertTrue(eventual_missing.perception_unreliable)

    def test_local_geometry_never_exceeds_planner_limit(self) -> None:
        pipeline = PerceptionPipeline(
            self.player_detector,
            self.geometry_detector,
            PlayerTracker(),
            GeometryFuser(),
            ScrollEstimator(),
            maximum_geometry_items=4,
        )
        snapshot = pipeline.process(frame(scene()))
        assert snapshot.local_geometry is not None
        self.assertLessEqual(snapshot.local_geometry.item_count, 4)

    def test_local_geometry_direct_conversion_requires_tracking(self) -> None:
        tracker = PlayerTracker()
        current = frame(scene())
        player = self.player_detector.detect(current)
        assert player is not None
        tracked = tracker.update(current, player)
        geometry = self.geometry_detector.detect(current, player)
        local = local_geometry_from_screen(tracked, geometry)
        self.assertGreaterEqual(len(local.floors), 1)
