from __future__ import annotations

import unittest
from math import isfinite

from geometry_dash_ai.tracking import GeometryFuser, PlayerTracker, ScrollEstimator
from geometry_dash_ai.vision import GeometryDetection, PlayerDetection, PlayerMode, ScreenBox
from tests.visual_fixtures import frame, scene


class TrackingTests(unittest.TestCase):
    def test_velocity_is_timestamp_driven_and_bounded(self) -> None:
        with self.assertRaisesRegex(ValueError, "maximum velocity"):
            PlayerTracker(maximum_velocity_px_s=True)
        tracker = PlayerTracker(maximum_velocity_px_s=100.0)
        first_frame = frame(scene(), 0, 1_000_000_000)
        second_frame = frame(scene(player_x=252), 1, 1_100_000_000)
        first = PlayerDetection(
            ScreenBox(50, 100, 20, 20), PlayerMode.CUBE, 1.0, 0, first_frame.timestamp_ns
        )
        second = PlayerDetection(
            ScreenBox(250, 100, 20, 20), PlayerMode.CUBE, 1.0, 1, second_frame.timestamp_ns
        )
        tracker.update(first_frame, first)
        tracked = tracker.update(second_frame, second)
        self.assertLessEqual(abs(tracked.vx), 100.0)
        with self.assertRaisesRegex(ValueError, "timestamps"):
            tracker.update(second_frame, second)

    def test_lost_and_reacquired_player(self) -> None:
        tracker = PlayerTracker()
        first_frame = frame(scene(), 0, 1_000_000_000)
        detection = PlayerDetection(
            ScreenBox(50, 100, 20, 20), PlayerMode.CUBE, 1.0, 0, first_frame.timestamp_ns
        )
        tracker.update(first_frame, detection)
        lost = tracker.update(frame(scene(include_player=False), 1, 1_100_000_000), None)
        self.assertGreater(lost.lost_seconds, 0.0)
        reacquired_frame = frame(scene(mode=PlayerMode.SHIP), 2, 1_200_000_000)
        reacquired = PlayerDetection(
            ScreenBox(55, 90, 20, 20), PlayerMode.SHIP, 1.0, 2, reacquired_frame.timestamp_ns
        )
        result = tracker.update(reacquired_frame, reacquired)
        self.assertEqual(result.lost_seconds, 0.0)

    def test_impossible_detection_is_treated_as_a_bounded_missing_frame(self) -> None:
        tracker = PlayerTracker(maximum_velocity_px_s=100.0)
        first_frame = frame(scene(), 0, 1_000_000_000)
        first = PlayerDetection(
            ScreenBox(50, 100, 20, 20), PlayerMode.CUBE, 1.0, 0, first_frame.timestamp_ns
        )
        tracker.update(first_frame, first)
        distractor_frame = frame(scene(), 1, 1_100_000_000)
        distractor = PlayerDetection(
            ScreenBox(250, 100, 20, 20), PlayerMode.CUBE, 1.0, 1, distractor_frame.timestamp_ns
        )
        tracked = tracker.update(distractor_frame, distractor)
        self.assertEqual(tracked.lost_frames, 1)
        self.assertGreater(tracked.lost_seconds, 0.0)
        self.assertIsNotNone(tracked.bounds)
        assert tracked.bounds is not None
        self.assertLess(tracked.bounds.x, 100.0)

    def test_missing_prediction_stops_after_its_bounded_reacquisition_window(self) -> None:
        tracker = PlayerTracker(maximum_velocity_px_s=100.0, maximum_missing_seconds=0.2)
        first_frame = frame(scene(), 0, 1_000_000_000)
        tracker.update(
            first_frame,
            PlayerDetection(
                ScreenBox(50, 100, 20, 20), PlayerMode.CUBE, 1.0, 0, first_frame.timestamp_ns
            ),
        )
        moving_frame = frame(scene(), 1, 1_100_000_000)
        tracker.update(
            moving_frame,
            PlayerDetection(
                ScreenBox(60, 100, 20, 20), PlayerMode.CUBE, 1.0, 1, moving_frame.timestamp_ns
            ),
        )
        briefly_missing = tracker.update(frame(scene(include_player=False), 2, 1_200_000_000), None)
        expired_missing = tracker.update(frame(scene(include_player=False), 3, 1_500_000_000), None)
        self.assertIsNotNone(briefly_missing.bounds)
        self.assertIsNotNone(expired_missing.bounds)
        assert briefly_missing.bounds is not None and expired_missing.bounds is not None
        self.assertEqual(expired_missing.bounds, briefly_missing.bounds)

    def test_mode_smoothing_rejects_one_frame_flicker_but_allows_transition(self) -> None:
        tracker = PlayerTracker(mode_history_frames=3)
        first_frame = frame(scene(), 0, 1_000_000_000)
        cube = PlayerDetection(
            ScreenBox(50, 100, 20, 20), PlayerMode.CUBE, 1.0, 0, first_frame.timestamp_ns
        )
        self.assertIs(tracker.update(first_frame, cube).mode, PlayerMode.CUBE)
        flicker_frame = frame(scene(), 1, 1_100_000_000)
        ship = PlayerDetection(
            ScreenBox(52, 100, 20, 20), PlayerMode.SHIP, 1.0, 1, flicker_frame.timestamp_ns
        )
        self.assertIs(tracker.update(flicker_frame, ship).mode, PlayerMode.CUBE)
        settled_frame = frame(scene(), 2, 1_200_000_000)
        settled_ship = PlayerDetection(
            ScreenBox(54, 100, 20, 20), PlayerMode.SHIP, 1.0, 2, settled_frame.timestamp_ns
        )
        self.assertIs(tracker.update(settled_frame, settled_ship).mode, PlayerMode.SHIP)

    def test_geometry_fuser_is_bounded(self) -> None:
        fuser = GeometryFuser(2)
        observation = GeometryDetection(floors=(ScreenBox(0, 100, 100, 2),), confidence=0.7)
        for _ in range(5):
            fuser.update(observation)
        self.assertEqual(fuser.cached_observations, 2)

    def test_scroll_uses_geometry_not_player(self) -> None:
        estimator = ScrollEstimator()
        first = GeometryDetection(solids=(ScreenBox(100, 80, 20, 20),), confidence=1.0)
        second = GeometryDetection(solids=(ScreenBox(90, 80, 20, 20),), confidence=1.0)
        estimator.update(first, 1_000_000_000)
        estimate = estimator.update(second, 1_100_000_000)
        self.assertAlmostEqual(estimate.scene_dx, -10.0)
        self.assertLess(estimate.speed_px_s, 0.0)

    def test_scroll_ignores_new_edge_anchor_instead_of_matching_by_list_position(self) -> None:
        estimator = ScrollEstimator(maximum_displacement_px=32.0)
        first = GeometryDetection(
            solids=(ScreenBox(100, 80, 20, 20), ScreenBox(220, 80, 20, 20)),
            confidence=1.0,
        )
        # A new object entering at the left changes detector ordering. The two
        # existing solids still moved left by two pixels.
        second = GeometryDetection(
            solids=(
                ScreenBox(20, 80, 20, 20),
                ScreenBox(98, 80, 20, 20),
                ScreenBox(218, 80, 20, 20),
            ),
            confidence=1.0,
        )
        estimator.update(first, 1_000_000_000)
        estimate = estimator.update(second, 1_016_666_667)
        self.assertAlmostEqual(estimate.scene_dx, -2.0)
        self.assertLess(estimate.speed_px_s, 0.0)

    def test_geometry_fusion_and_scroll_stay_bounded_during_long_smooth_scroll(self) -> None:
        fuser = GeometryFuser(12)
        estimator = ScrollEstimator(maximum_displacement_px=16.0)
        estimate = None
        for frame_index in range(1_000):
            offset = float(-2 * frame_index)
            geometry = GeometryDetection(
                floors=(ScreenBox(offset, 140, 180, 2),),
                solids=(ScreenBox(220 + offset, 92, 32, 48),),
                confidence=0.8,
            )
            fused = fuser.update(geometry)
            estimate = estimator.update(fused, 1_000_000_000 + frame_index * 16_666_667)
            self.assertLessEqual(fuser.cached_observations, 12)
            self.assertLessEqual(len(fused.floors) + len(fused.solids), 2)
            self.assertTrue(isfinite(estimate.scene_dx))
            self.assertTrue(isfinite(estimate.speed_px_s))
        assert estimate is not None
        self.assertAlmostEqual(estimate.scene_dx, -2.0, delta=0.1)
