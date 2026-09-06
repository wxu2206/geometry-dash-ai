from __future__ import annotations

import unittest

from geometry_dash_ai.app.demo import run_demo


class AlphaIntegrationTests(unittest.TestCase):
    def test_pixels_only_cube_ship_cube_demo_completes(self) -> None:
        result = run_demo()
        self.assertTrue(result.completed)
        self.assertEqual(result.transitions, ("cube->ship", "ship->cube"))
        self.assertLessEqual(result.frames, 360)
        self.assertGreater(result.input_events, 0)


if __name__ == "__main__":
    unittest.main()
