from __future__ import annotations

import unittest

from geometry_dash_ai.config.settings import AppConfig
from geometry_dash_ai.vision.__main__ import build_pipeline
from geometry_dash_ai.vision.run_state import (
    RunPhase,
    VisualRunStateObserver,
    detect_completion_visual_cue,
)
from tests.visual_fixtures import frame, scene


class VisualRunStateTests(unittest.TestCase):
    def test_one_missing_frame_is_not_death_and_temporal_loss_is(self) -> None:
        pipeline = build_pipeline(AppConfig())
        observer = VisualRunStateObserver()
        timestamp = 1_000_000_000
        for sequence in range(2):
            snapshot = pipeline.process(frame(scene(), sequence, timestamp))
            observation = observer.update(snapshot)
            timestamp += 100_000_000
        self.assertIs(observation.phase, RunPhase.ACTIVE)
        missing = pipeline.process(frame(scene(include_player=False), 2, timestamp))
        self.assertIsNot(observer.update(missing).phase, RunPhase.DEAD)
        for sequence in range(3, 6):
            timestamp += 150_000_000
            missing = pipeline.process(
                frame(scene(include_player=False), sequence, timestamp)
            )
            observation = observer.update(missing)
        self.assertIs(observation.phase, RunPhase.DEAD)
        self.assertGreaterEqual(observation.confidence, 0.55)

    def test_completion_requires_active_run_and_visual_green_panel(self) -> None:
        image = scene()
        image[5:45, 80:240] = (30, 220, 60)
        current = frame(image)
        self.assertTrue(detect_completion_visual_cue(current))
        observer = VisualRunStateObserver()
        pipeline = build_pipeline(AppConfig())
        first = pipeline.process(frame(scene(), 0, 1_000_000_000))
        observer.update(first, completion_visual_cue=True)
        self.assertIs(observer.update(first).phase, RunPhase.ACTIVE)
        completed = observer.update(first, completion_visual_cue=True)
        self.assertIs(completed.phase, RunPhase.COMPLETE)


if __name__ == "__main__":
    unittest.main()
