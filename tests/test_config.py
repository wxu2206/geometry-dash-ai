import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from geometry_dash_ai.calibrate import sample_player_color
from geometry_dash_ai.config.settings import ConfigError, config_from_dict, load_config


class ConfigTests(unittest.TestCase):
    def test_default_configuration_loads_safely(self) -> None:
        config = load_config(Path("config/default.toml"))

        self.assertEqual(config.capture.target_fps, 60)
        self.assertEqual(config.capture.width, 1280)
        self.assertFalse(config.control.enabled)
        self.assertEqual(config.control.emergency_stop_key, "f12")
        self.assertEqual(config.planning.maximum_candidates, 16)
        self.assertEqual(config.planning.maximum_jump_delay_frames, 24)
        self.assertEqual(config.vision.cube_color, (255, 60, 200))
        self.assertEqual(config.capture.backend, "portal")

    def test_local_configuration_overrides_one_value(self) -> None:
        with TemporaryDirectory() as directory:
            local = Path(directory) / "local.toml"
            local.write_text("[capture]\nleft = 42\n", encoding="utf-8")

            config = load_config(Path("config/default.toml"), local)

        self.assertEqual(config.capture.left, 42)
        self.assertEqual(config.capture.height, 720)

    def test_invalid_capture_size_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigError, "capture.width"):
            config_from_dict({"capture": {"width": 0}})

    def test_unknown_setting_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigError, "unknown setting"):
            config_from_dict({"control": {"unsafe_magic": True}})

    def test_non_finite_planner_config_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigError, "finite"):
            config_from_dict({"planning": {"horizon_seconds": math.nan}})

    def test_invalid_control_key_type_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigError, "non-empty string"):
            config_from_dict({"control": {"emergency_stop_key": 12}})

    def test_extreme_numeric_config_is_rejected_without_overflow(self) -> None:
        with self.assertRaisesRegex(ConfigError, "finite"):
            config_from_dict({"control": {"action_interval_ms": 10**10_000}})

    def test_capture_and_vision_bounds_are_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigError, "target_fps"):
            config_from_dict({"capture": {"target_fps": 241}})
        with self.assertRaisesRegex(ConfigError, "finite"):
            config_from_dict({"vision": {"maximum_velocity_px_s": math.inf}})
        with self.assertRaisesRegex(ConfigError, "preview_scale"):
            config_from_dict({"capture": {"preview_scale": 0.01}})
        with self.assertRaisesRegex(ConfigError, "RGB"):
            config_from_dict({"vision": {"cube_color": [True, 60, 200]}})
        with self.assertRaisesRegex(ConfigError, "capture.backend"):
            config_from_dict({"capture": {"backend": "untrusted"}})

    def test_player_color_sampling_is_bounded_and_robust(self) -> None:
        image = np.zeros((4, 4, 3), dtype=np.uint8)
        image[1:3, 1:3] = (250, 50, 200)
        self.assertEqual(sample_player_color(image, (1, 1, 2, 2)), (250, 50, 200))
        with self.assertRaisesRegex(ValueError, "exceed"):
            sample_player_color(image, (3, 3, 2, 2))


if __name__ == "__main__":
    unittest.main()
