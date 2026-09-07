"""One coherent command-line entry point for the alpha application."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from geometry_dash_ai.app.benchmark import run_benchmarks
from geometry_dash_ai.app.demo import run_demo
from geometry_dash_ai.app.doctor import run_doctor
from geometry_dash_ai.app.ipc import LocalRuntimeFiles
from geometry_dash_ai.app.ui import AlphaLocalWebApplication, AlphaUiUnavailable
from geometry_dash_ai.calibrate import main as calibrate_main
from geometry_dash_ai.config.settings import ConfigError, load_config
from geometry_dash_ai.vision.__main__ import main as observe_main


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geometry-dash-ai",
        description="Local vision, planning, calibration, and guarded Geometry Dash control",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("doctor", "calibrate", "observe", "shadow", "stop", "demo", "benchmark"),
        help="omit to open the application dashboard",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in {"calibrate", "observe", "shadow"}:
        command, tail = arguments[0], arguments[1:]
        if command == "calibrate":
            return calibrate_main(tail)
        if command == "shadow":
            tail.append("--shadow")
            if "--shadow-log" not in tail:
                tail.extend(("--shadow-log", "shadow.jsonl"))
        return observe_main(tail)
    args = _parser().parse_args(arguments)
    root = Path.cwd().resolve()
    if args.command == "doctor":
        checks = run_doctor(root)
        for check in checks:
            print(f"{check.level.value:<4} {check.name}: {check.detail}")
        return 1 if any(check.level.value == "FAIL" for check in checks) else 0
    if args.command == "stop":
        LocalRuntimeFiles().request_stop()
        print("Emergency Stop requested for the local Geometry Dash AI application.")
        return 0
    if args.command == "demo":
        result = run_demo()
        print(
            f"synthetic alpha demo: completed={result.completed} frames={result.frames} "
            f"transitions={','.join(result.transitions)} input_events={result.input_events} "
            f"elapsed_ms={result.elapsed_ms:.2f}"
        )
        return 0 if result.completed else 2
    if args.command == "benchmark":
        for benchmark in run_benchmarks():
            print(
                f"{benchmark.name}: {benchmark.rate_hz:.1f} Hz "
                f"({benchmark.total_ms:.2f} ms total)"
            )
        return 0
    try:
        local = root / "config" / "local.toml"
        config = load_config(root / "config" / "default.toml", local if local.exists() else None)
        application = AlphaLocalWebApplication(config, root)
        application.run()
    except (ConfigError, AlphaUiUnavailable, RuntimeError) as exc:
        print(f"Geometry Dash AI could not start: {exc}")
        print("Run 'geometry-dash-ai doctor' for a sanitized environment report.")
        return 2
    return 0
