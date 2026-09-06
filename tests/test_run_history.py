from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from geometry_dash_ai.telemetry import RunHistoryStore, RunSummary


class RunHistoryTests(unittest.TestCase):
    def test_history_is_bounded_validated_and_skips_corrupt_lines(self) -> None:
        with TemporaryDirectory() as directory:
            store = RunHistoryStore(Path(directory), maximum_bytes=4_096)
            for attempt in range(1, 40):
                store.append(
                    RunSummary(attempt, attempt, attempt + 1, "dead", "cube", "spike", 0.8, 1)
                )
            self.assertLessEqual(store.path.stat().st_size, 4_096)
            with store.path.open("ab") as stream:
                stream.write(b"not-json\n")
            recent = store.recent(10)
            self.assertLessEqual(len(recent), 9)
            self.assertTrue(all(isinstance(item, RunSummary) for item in recent))

    def test_invalid_summary_and_read_limit_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RunSummary(0, 0, 0, "dead", "cube", None, 0.5, 0)
        with TemporaryDirectory() as directory, self.assertRaises(ValueError):
            RunHistoryStore(Path(directory)).recent(501)


if __name__ == "__main__":
    unittest.main()
