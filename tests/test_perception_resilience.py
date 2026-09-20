from __future__ import annotations

import unittest

import numpy as np

from geometry_dash_ai.simulation import Simulator, scenario_catalog
from geometry_dash_ai.simulation.render import render_step
from geometry_dash_ai.vision import ClassicalGeometryDetector, ClassicalPlayerDetector
from tests.visual_fixtures import frame, scene


class PerceptionResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.player_detector = ClassicalPlayerDetector()
        self.geometry_detector = ClassicalGeometryDetector()

    def test_small_brightness_and_translation_changes_preserve_interpretation(self) -> None:
        original = scene(noise=True)
        dimmed = np.rint(original.astype(np.float32) * 0.9).astype(np.uint8)
        shifted = np.full_like(original, (18, 24, 40))
        shifted[:, 3:] = original[:, :-3]
        baseline_player = self.player_detector.detect(frame(original))
        baseline_geometry = self.geometry_detector.detect(frame(original), baseline_player)
        assert baseline_player is not None
        for variant, expected_shift in ((dimmed, 0.0), (shifted, 3.0)):
            with self.subTest(expected_shift=expected_shift):
                detected_player = self.player_detector.detect(frame(variant))
                geometry = self.geometry_detector.detect(frame(variant), detected_player)
                self.assertIsNotNone(detected_player)
                assert detected_player is not None
                self.assertAlmostEqual(
                    detected_player.bounds.x - baseline_player.bounds.x,
                    expected_shift,
                    delta=2.0,
                )
                self.assertEqual(bool(geometry.spikes), bool(baseline_geometry.spikes))
                self.assertEqual(bool(geometry.floors), bool(baseline_geometry.floors))

    def test_far_player_colored_distractor_loses_to_temporal_prior(self) -> None:
        image = scene()
        image[40:64, 270:294] = (255, 60, 200)
        prior = self.player_detector.detect(frame(scene()))
        assert prior is not None
        detected = self.player_detector.detect(frame(image), prior.bounds)
        self.assertIsNotNone(detected)
        assert detected is not None
        self.assertLess(detected.bounds.x, 100.0)

    def test_floor_unsupported_red_decoration_is_not_a_spike(self) -> None:
        image = scene(include_spike=False)
        for offset in range(20):
            half = max(1, (offset + 1) // 2)
            image[70 - offset, 160 - half : 160 + half] = (250, 45, 35)
        detected_player = self.player_detector.detect(frame(image))
        geometry = self.geometry_detector.detect(frame(image), detected_player)
        self.assertEqual(geometry.spikes, ())

    def test_adjacent_triple_spikes_remain_three_hazards_after_rendering(self) -> None:
        scenario = next(item for item in scenario_catalog() if item.name == "triple_spike")
        rendered = render_step(
            Simulator(scenario.level, initial_state=scenario.initial_state).reset(),
            scenario.level,
            0,
            1_000_000_000,
        )
        player = self.player_detector.detect(rendered)
        geometry = self.geometry_detector.detect(rendered, player)
        self.assertEqual(len(geometry.spikes), 3)


if __name__ == "__main__":
    unittest.main()
