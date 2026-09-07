from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import patch

import numpy as np

from geometry_dash_ai.app.ipc import LocalRuntimeFiles
from geometry_dash_ai.app.ui import LOOPBACK_HOST, MAX_PREVIEW_BYTES, AlphaLocalWebApplication
from geometry_dash_ai.config.settings import AppConfig
from geometry_dash_ai.vision.pipeline import PerceptionSnapshot


class LocalWebUiTests(unittest.TestCase):
    def _application(
        self, root: Path, config: AppConfig | None = None
    ) -> AlphaLocalWebApplication:
        (root / "config").mkdir()
        return AlphaLocalWebApplication(
            AppConfig() if config is None else config, root, LocalRuntimeFiles(root / "runtime")
        )

    @staticmethod
    def _setup_payload() -> dict[str, object]:
        return {
            "crop_left": 0,
            "crop_top": 0,
            "crop_width": 320,
            "crop_height": 180,
            "target_fps": 60,
            "color_tolerance": 72,
            "maximum_attempts": 3,
            "live_control": False,
            "auto_retry": True,
            "recording": False,
            "calibration": True,
        }

    def test_starts_without_tk_and_binds_only_loopback(self) -> None:
        class FakeServer:
            def __init__(self, address: tuple[str, int], handler: object) -> None:
                self.requested_address = address
                self.handler = handler
                self.server_address = (LOOPBACK_HOST, 49152)
                self.closed = False

            def server_close(self) -> None:
                self.closed = True

        with TemporaryDirectory() as directory:
            application = self._application(Path(directory))
            self.assertEqual(application.status_payload()["status"], "SETUP_REQUIRED")
            with patch("geometry_dash_ai.app.ui._LoopbackServer", FakeServer):
                url = application.start_server()
            self.assertTrue(url.startswith(f"http://{LOOPBACK_HOST}:"))
            self.assertNotIn("0.0.0.0", url)
            application.close()

    def test_status_setup_reset_and_emergency_routing_are_serializable(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            application = self._application(root)
            initial = application.status_payload()
            json.dumps(initial)
            self.assertFalse(initial["buttons"]["observe"])
            saved = application.dispatch("setup", self._setup_payload())
            self.assertTrue(saved["ok"])
            self.assertTrue((root / "config" / "local.toml").exists())
            self.assertEqual(application.status_payload()["status"], "READY")
            self.assertTrue(application.dispatch("reset", {})["ok"])
            self.assertFalse((root / "config" / "local.toml").exists())
            stopped = application.dispatch("emergency_stop", {})
            self.assertTrue(stopped["ok"])
            self.assertEqual(application.status_payload()["status"], "STOPPED")
            application.close()

    def test_invalid_setup_and_disallowed_actions_fail_without_side_effects(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            application = self._application(root)
            malformed = self._setup_payload()
            malformed["crop_width"] = True
            result = application.dispatch("setup", malformed)
            self.assertFalse(result["ok"])
            self.assertFalse((root / "config" / "local.toml").exists())
            result = application.dispatch("start", {})
            self.assertFalse(result["ok"])
            self.assertIn("unavailable", str(result["error"]))
            application.close()

    def test_shadow_state_renders_the_no_input_banner_and_control_route(self) -> None:
        with TemporaryDirectory() as directory:
            application = self._application(Path(directory))
            application.dispatch("setup", self._setup_payload())
            with application._supervisor_lock:
                application._supervisor.begin_capture()
                application._supervisor.capture_ready()
                application._supervisor.enter_shadow()
            status = application.status_payload()
            self.assertEqual(status["banner"], "SHADOW MODE — NO INPUT")
            self.assertTrue(status["buttons"]["request_control"])
            self.assertFalse(status["buttons"]["start"])
            application.close()

    def test_preview_is_bounded_and_diagnostics_are_sanitized(self) -> None:
        with TemporaryDirectory() as directory:
            application = self._application(Path(directory))
            image = np.zeros((180, 320, 3), dtype=np.uint8)
            application._latest.append((cast(PerceptionSnapshot, None), image))
            preview = application.preview_bmp()
            assert preview is not None
            self.assertTrue(preview.startswith(b"BM"))
            self.assertLessEqual(len(preview), MAX_PREVIEW_BYTES)
            diagnostics = application.diagnostics_payload()
            json.dumps(diagnostics)
            self.assertNotIn("token", json.dumps(diagnostics).lower())
            application.close()

    def test_capture_worker_publishes_latest_snapshot_for_dashboard_actions(self) -> None:
        with TemporaryDirectory() as directory:
            config = replace(
                AppConfig(),
                capture=replace(AppConfig().capture, backend="synthetic", width=320, height=180),
            )
            application = self._application(Path(directory), config)
            application.dispatch("setup", self._setup_payload())
            application.dispatch("observe", {})
            assert application._worker is not None
            application._worker.join(timeout=1.0)
            self.assertIsNotNone(application._last_snapshot)
            application.close()


if __name__ == "__main__":
    unittest.main()
