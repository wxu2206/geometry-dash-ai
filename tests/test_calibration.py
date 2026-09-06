from __future__ import annotations

import math
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from geometry_dash_ai.capture import CapturedFrame, CaptureRegion
from geometry_dash_ai.learning import (
    AirborneSample,
    CalibrationInvalid,
    CalibrationStore,
    CubePhysicsCalibrator,
    PhysicsCalibration,
    VisualCubeCalibrationCollector,
)
from geometry_dash_ai.tracking import ScrollEstimate, TrackedPlayer
from geometry_dash_ai.vision import GeometryDetection, PlayerMode, ScreenBox
from geometry_dash_ai.vision.pipeline import PerceptionMetrics, PerceptionSnapshot


class CalibrationTests(unittest.TestCase):
    def test_known_ballistic_parameters_are_recovered_with_outlier(self) -> None:
        samples = []
        for index in range(21):
            time = index * 0.025
            y = 10.0 + 480.0 * time + 0.5 * -1_300.0 * time * time
            if index == 10:
                y += 200.0
            samples.append(AirborneSample(time, y, 0.9))
        result = CubePhysicsCalibrator(minimum_samples=12).fit_airborne(tuple(samples))
        self.assertAlmostEqual(result.gravity, -1_300.0, delta=1.0)
        self.assertAlmostEqual(result.jump_velocity, 480.0, delta=1.0)
        self.assertGreaterEqual(result.sample_count, 20)

    def test_insufficient_nonfinite_and_bounds_are_rejected(self) -> None:
        with self.assertRaises(CalibrationInvalid):
            CubePhysicsCalibrator().fit_airborne(
                tuple(AirborneSample(index * 0.02, 0.0, 0.9) for index in range(5))
            )
        with self.assertRaises(CalibrationInvalid):
            AirborneSample(math.nan, 1.0, 1.0)
        with self.assertRaises(CalibrationInvalid):
            PhysicsCalibration(gravity=1.0)

    def test_large_error_rolls_back_and_good_fit_is_promoted(self) -> None:
        calibrator = CubePhysicsCalibrator(minimum_samples=6, learning_rate=0.1)
        candidate = PhysicsCalibration(sample_count=20, revision=1, gravity=-1_200.0)
        promoted = calibrator.adapt(candidate, observed_error_px=4.0)
        self.assertEqual(calibrator.last_known_good, promoted)
        calibrator.current = PhysicsCalibration(gravity=-5_000.0)
        self.assertEqual(calibrator.adapt(candidate, 120.0), promoted)

    def test_versioned_persistence_permissions_and_corrupt_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CalibrationStore(root)
            current = PhysicsCalibration(sample_count=20, revision=2)
            store.save(current, PhysicsCalibration())
            loaded, known = store.load()
            self.assertEqual(loaded, current)
            self.assertEqual(known, PhysicsCalibration())
            self.assertEqual(os.stat(store.path).st_mode & 0o777, 0o600)
            store.path.write_text("not json", encoding="utf-8")
            with self.assertRaises(CalibrationInvalid):
                store.load()

    def test_symlink_write_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("keep", encoding="utf-8")
            store = CalibrationStore(root)
            store.path.parent.mkdir(parents=True)
            store.path.symlink_to(target)
            with self.assertRaisesRegex(CalibrationInvalid, "symlink"):
                store.save(PhysicsCalibration(), PhysicsCalibration())
            self.assertEqual(target.read_text(encoding="utf-8"), "keep")

    def test_visual_manual_jump_collection_saves_a_valid_model(self) -> None:
        with TemporaryDirectory() as directory:
            store = CalibrationStore(Path(directory))
            collector = VisualCubeCalibrationCollector(store, minimum_samples=20)
            result = None
            for index in range(31):
                time = index * 0.0125
                screen_y = 100.0 - 480.0 * time + 650.0 * time * time
                timestamp = 1_000_000_000 + round(time * 1_000_000_000)
                captured = CapturedFrame(
                    np.zeros((2, 2, 3), dtype=np.uint8),
                    timestamp,
                    index,
                    CaptureRegion(0, 0, 2, 2),
                )
                tracked = TrackedPlayer(
                    ScreenBox(0.0, screen_y, 24.0, 24.0),
                    0.0,
                    -480.0 + 1_300.0 * time,
                    PlayerMode.CUBE,
                    0.9,
                    0.0,
                    index,
                    timestamp,
                    age_frames=index + 1,
                )
                geometry = GeometryDetection(confidence=0.8)
                snapshot = PerceptionSnapshot(
                    captured,
                    None,
                    tracked,
                    geometry,
                    geometry,
                    None,
                    ScrollEstimate(-3.0, -180.0, 0.8, timestamp),
                    False,
                    PerceptionMetrics(60.0, 1.0, 1.0, index + 1),
                )
                result = collector.update(snapshot) or result
            self.assertIsNotNone(result)
            self.assertTrue(collector.ready)
            self.assertTrue(store.path.exists())

    def test_symlink_calibration_directory_is_rejected(self) -> None:
        with TemporaryDirectory() as directory, TemporaryDirectory() as outside:
            root = Path(directory)
            (root / "data").mkdir()
            (root / "data" / "calibration").symlink_to(Path(outside), target_is_directory=True)
            with self.assertRaisesRegex(CalibrationInvalid, "symlink"):
                CalibrationStore(root)


if __name__ == "__main__":
    unittest.main()
