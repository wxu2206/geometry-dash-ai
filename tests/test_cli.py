from __future__ import annotations

import unittest
from unittest.mock import patch

from geometry_dash_ai.app.benchmark import BenchmarkResult
from geometry_dash_ai.app.cli import main
from geometry_dash_ai.app.demo import DemoResult
from geometry_dash_ai.app.doctor import CheckLevel, DoctorCheck


class CommandLineTests(unittest.TestCase):
    def test_read_only_commands_route_without_starting_the_ui(self) -> None:
        with patch(
            "geometry_dash_ai.app.cli.run_doctor",
            return_value=(DoctorCheck("Portal", CheckLevel.WARN, "unavailable"),),
        ):
            self.assertEqual(main(["doctor"]), 0)
        with patch(
            "geometry_dash_ai.app.cli.run_demo",
            return_value=DemoResult(True, 10, ("cube->ship",), 2, 1.0),
        ):
            self.assertEqual(main(["demo"]), 0)
        with patch(
            "geometry_dash_ai.app.cli.run_benchmarks",
            return_value=(BenchmarkResult("test", 1, 1.0),),
        ):
            self.assertEqual(main(["benchmark"]), 0)

    def test_observe_shadow_calibrate_and_stop_use_fixed_routes(self) -> None:
        with patch("geometry_dash_ai.app.cli.observe_main", return_value=0) as observe:
            self.assertEqual(main(["observe", "--frames", "2"]), 0)
            observe.assert_called_once_with(["--frames", "2"])
        with patch("geometry_dash_ai.app.cli.observe_main", return_value=0) as shadow:
            self.assertEqual(main(["shadow", "--frames", "2"]), 0)
            shadow.assert_called_once_with(
                ["--frames", "2", "--shadow", "--shadow-log", "shadow.jsonl"]
            )
        with patch("geometry_dash_ai.app.cli.calibrate_main", return_value=0) as calibrate:
            self.assertEqual(main(["calibrate", "--backend", "synthetic"]), 0)
            calibrate.assert_called_once_with(["--backend", "synthetic"])
        with patch("geometry_dash_ai.app.cli.LocalRuntimeFiles") as runtime_files:
            self.assertEqual(main(["stop"]), 0)
            runtime_files.return_value.request_stop.assert_called_once()

    def test_bad_command_exits_cleanly_before_any_control_or_ui_route(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            main(["not-a-command"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
