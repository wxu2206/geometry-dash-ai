from __future__ import annotations

import unittest

import numpy as np

from geometry_dash_ai.capture import (
    CapturedFrame,
    CaptureRegion,
    LatestFrameBuffer,
    SyntheticFrameSource,
)
from geometry_dash_ai.vision.components import components


class CaptureTests(unittest.TestCase):
    def test_frame_validation_rejects_malformed_or_huge_input(self) -> None:
        region = CaptureRegion(0, 0, 4, 4)
        with self.assertRaisesRegex(ValueError, "uint8"):
            CapturedFrame(np.zeros((4, 4, 3), dtype=np.float32), 1, 0, region)
        with self.assertRaisesRegex(ValueError, "shape"):
            CapturedFrame(np.zeros((4, 4), dtype=np.uint8), 1, 0, region)
        with self.assertRaisesRegex(ValueError, "width"):
            CaptureRegion(0, 0, 7_681, 1)

    def test_latest_buffer_drops_stale_frames(self) -> None:
        region = CaptureRegion(0, 0, 4, 4)
        image = np.zeros((4, 4, 3), dtype=np.uint8)
        buffer = LatestFrameBuffer(1)
        first = CapturedFrame(image, 1, 0, region)
        latest = CapturedFrame(image, 2, 1, region)
        buffer.publish(first)
        buffer.publish(latest)
        self.assertEqual(buffer.take_latest(), latest)
        self.assertGreaterEqual(buffer.metrics.dropped, 1)

    def test_synthetic_source_is_bounded_and_closes(self) -> None:
        region = CaptureRegion(0, 0, 4, 4)
        source = SyntheticFrameSource(region, (np.zeros((4, 4, 3), dtype=np.uint8),))
        self.assertEqual(source.capture_once().sequence, 0)
        source.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            source.capture_once()

    def test_component_extraction_rejects_unbounded_requests_before_point_allocation(self) -> None:
        mask = np.ones((400, 400), dtype=np.bool_)
        self.assertEqual(components(mask, 1), ())
        with self.assertRaisesRegex(ValueError, "maximum component"):
            components(mask, 1, 100_001)
