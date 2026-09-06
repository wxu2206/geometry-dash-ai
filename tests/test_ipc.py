from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from geometry_dash_ai.app.ipc import ControlInstanceBusy, LocalRuntimeFiles


class LocalIpcTests(unittest.TestCase):
    def test_stop_flag_is_owner_only_and_consumed_once(self) -> None:
        with TemporaryDirectory() as directory:
            runtime = LocalRuntimeFiles(Path(directory) / "runtime")
            runtime.request_stop()
            self.assertEqual(os.stat(runtime.stop_path).st_mode & 0o777, 0o600)
            self.assertTrue(runtime.consume_stop())
            self.assertFalse(runtime.consume_stop())

    def test_only_one_control_owner_is_allowed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            first = LocalRuntimeFiles(root)
            second = LocalRuntimeFiles(root)
            first.acquire_control()
            with self.assertRaises(ControlInstanceBusy):
                second.acquire_control()
            first.release_control()
            second.acquire_control()
            second.release_control()

    def test_symlink_stop_target_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            runtime = LocalRuntimeFiles(Path(directory) / "runtime")
            target = Path(directory) / "unrelated"
            target.write_text("safe", encoding="utf-8")
            runtime.stop_path.symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                runtime.request_stop()
            self.assertEqual(target.read_text(encoding="utf-8"), "safe")


if __name__ == "__main__":
    unittest.main()
