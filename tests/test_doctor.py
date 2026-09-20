from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from geometry_dash_ai.app.doctor import _missing_pipewire_plugins


class DoctorTests(unittest.TestCase):
    def test_pipewire_reader_check_requires_every_fixed_pipeline_element(self) -> None:
        inspected: list[str] = []

        def inspect(command: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
            inspected.append(command[1])
            return subprocess.CompletedProcess(command, 0)

        with (
            patch(
                "geometry_dash_ai.app.doctor.shutil.which",
                return_value="/usr/bin/gst-inspect-1.0",
            ),
            patch("geometry_dash_ai.app.doctor.subprocess.run", side_effect=inspect),
        ):
            self.assertEqual(_missing_pipewire_plugins(), ())
        self.assertEqual(
            inspected,
            ["pipewiresrc", "queue", "videoconvert", "videocrop", "fdsink"],
        )

    def test_pipewire_reader_check_reports_missing_or_timed_out_elements(self) -> None:
        def inspect(command: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
            if command[1] == "videocrop":
                raise subprocess.TimeoutExpired(command, 3.0)
            return subprocess.CompletedProcess(command, 1 if command[1] == "fdsink" else 0)

        with (
            patch(
                "geometry_dash_ai.app.doctor.shutil.which",
                return_value="/usr/bin/gst-inspect-1.0",
            ),
            patch("geometry_dash_ai.app.doctor.subprocess.run", side_effect=inspect),
        ):
            self.assertEqual(_missing_pipewire_plugins(), ("videocrop", "fdsink"))

    def test_pipewire_reader_check_handles_missing_inspector(self) -> None:
        with patch("geometry_dash_ai.app.doctor.shutil.which", return_value=None):
            self.assertEqual(_missing_pipewire_plugins(), ("gst-inspect-1.0",))
