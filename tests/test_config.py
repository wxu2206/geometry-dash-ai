import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from geometry_dash_ai.config.settings import ConfigError, config_from_dict, load_config


class ConfigTests(unittest.TestCase):
    def test_default_configuration_loads_safely(self) -> None:
        config = load_config(Path("config/default.toml"))

        self.assertEqual(config.capture.target_fps, 60)
        self.assertEqual(config.capture.width, 1280)
        self.assertFalse(config.control.enabled)
        self.assertEqual(config.control.emergency_stop_key, "f12")

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


if __name__ == "__main__":
    unittest.main()
