import gzip
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from geometry_dash_ai.physics import CollisionType
from geometry_dash_ai.planning import CubeAction
from geometry_dash_ai.simulation import Action, GameMode, SimulationStatus
from geometry_dash_ai.telemetry import JsonlTelemetryWriter, TelemetryEvent


class TelemetryTests(unittest.TestCase):
    def test_string_enums_keep_json_and_string_compatibility(self) -> None:
        values = {
            "collision": CollisionType.SPIKE,
            "cube_action": CubeAction.JUMP,
            "game_mode": GameMode.CUBE,
            "simulation_action": Action.PRESS,
            "simulation_status": SimulationStatus.DEAD,
        }

        self.assertEqual(
            json.loads(json.dumps(values)),
            {
                "collision": "spike",
                "cube_action": "jump",
                "game_mode": "cube",
                "simulation_action": "press",
                "simulation_status": "dead",
            },
        )
        self.assertEqual(str(GameMode.CUBE), "cube")

    def test_telemetry_round_trip(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "run.jsonl"
            event = TelemetryEvent(
                event="player_state",
                monotonic_ns=123,
                wall_time="2026-01-01T00:00:00+00:00",
                payload={"mode": GameMode.CUBE, "confidence": 0.93},
            )
            with JsonlTelemetryWriter(path) as writer:
                writer.write(event)
            decoded = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(decoded["schema_version"], 1)
        self.assertEqual(decoded["event"], "player_state")
        self.assertEqual(decoded["payload"]["mode"], "cube")

    def test_compressed_telemetry(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "run.jsonl.gz"
            with JsonlTelemetryWriter(path) as writer:
                writer.write(TelemetryEvent("attempt_started", 10, {"attempt": 1}))
            with gzip.open(path, mode="rt", encoding="utf-8") as stream:
                payload = json.loads(stream.readline())["payload"]

        self.assertEqual(payload["attempt"], 1)

    def test_writer_requires_context_manager(self) -> None:
        with TemporaryDirectory() as directory:
            writer = JsonlTelemetryWriter(Path(directory) / "run.jsonl")
            with self.assertRaisesRegex(RuntimeError, "context manager"):
                writer.write(TelemetryEvent("test", 0, {}))


if __name__ == "__main__":
    unittest.main()
