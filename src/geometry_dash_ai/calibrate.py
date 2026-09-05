"""Manual, observe-only capture-region setup utility."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from geometry_dash_ai.capture import CaptureRegion, CaptureUnavailable, MssFrameSource


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a Geometry Dash capture rectangle without input"
    )
    parser.add_argument("--left", type=int, required=True)
    parser.add_argument("--top", type=int, required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--target-fps", type=int, default=60)
    parser.add_argument(
        "--write-local",
        action="store_true",
        help="write only config/local.toml after capture validation",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    region = CaptureRegion(args.left, args.top, args.width, args.height)
    try:
        source = MssFrameSource(region, args.target_fps)
        frame = source.capture_once()
        source.close()
    except CaptureUnavailable as exc:
        print(f"capture unavailable: {exc}")
        return 2
    dimensions = f"{frame.width}x{frame.height}"
    position = f"({region.left}, {region.top})"
    print(f"validated region {dimensions} at {position}; observe-only")
    if args.write_local:
        _write_local(region, args.target_fps)
        print("wrote validated capture settings to config/local.toml")
    return 0


def _write_local(region: CaptureRegion, target_fps: int) -> None:
    root = Path.cwd().resolve()
    candidate = root / "config" / "local.toml"
    if candidate.is_symlink() or candidate.parent.is_symlink():
        raise ValueError("refusing to write through a calibration symlink")
    destination = candidate.resolve()
    if root not in destination.parents:
        raise ValueError("refusing to write calibration outside config/local.toml")
    content = (
        "[capture]\n"
        f"left = {region.left}\n"
        f"top = {region.top}\n"
        f"width = {region.width}\n"
        f"height = {region.height}\n"
        f"target_fps = {target_fps}\n"
    )
    destination.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
