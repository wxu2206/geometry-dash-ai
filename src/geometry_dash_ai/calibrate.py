"""Manual, observe-only capture-region setup utility."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from geometry_dash_ai.capture import (
    CaptureRegion,
    CaptureUnavailable,
    MssFrameSource,
    PipeWirePortalFrameSource,
)
from geometry_dash_ai.capture.source import FrameSource


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a Geometry Dash capture rectangle without input"
    )
    parser.add_argument("--backend", choices=("portal", "mss"), default="portal")
    parser.add_argument("--left", type=int, default=0)
    parser.add_argument("--top", type=int, default=0)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--target-fps", type=int, default=60)
    parser.add_argument(
        "--write-local",
        action="store_true",
        help="write only config/local.toml after capture validation",
    )
    parser.add_argument(
        "--sample-player",
        type=int,
        nargs=4,
        metavar=("LEFT", "TOP", "WIDTH", "HEIGHT"),
        help="sample a manually selected cube-color rectangle from the approved frame",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if (args.width is None) != (args.height is None):
        raise ValueError("width and height must be supplied together")
    region = (
        None
        if args.width is None
        else CaptureRegion(args.left, args.top, args.width, args.height)
    )
    if args.backend == "mss" and region is None:
        raise ValueError("mss calibration requires --width and --height")
    source: FrameSource | None = None
    try:
        if args.backend == "portal":
            source = PipeWirePortalFrameSource(region, args.target_fps)
        else:
            assert region is not None
            source = MssFrameSource(region, args.target_fps)
        frame = source.capture_once()
    except CaptureUnavailable as exc:
        print(f"capture unavailable: {exc}")
        return 2
    finally:
        if source is not None:
            source.close()
    assert source is not None
    dimensions = f"{frame.width}x{frame.height}"
    selected_region = source.region
    position = f"({selected_region.left}, {selected_region.top})"
    print(f"validated region {dimensions} at {position}; observe-only")
    sampled_color = None
    if args.sample_player is not None:
        sampled_color = sample_player_color(frame.image, tuple(args.sample_player))
        print(f"sampled cube RGB={sampled_color}; verify it in the observe-only preview")
    if args.write_local:
        _write_local(selected_region, args.target_fps, args.backend, sampled_color)
        print("wrote validated capture settings to config/local.toml")
    return 0


def sample_player_color(image: object, bounds: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """Robustly sample a manually selected player patch without retaining the frame."""
    if (
        not isinstance(image, np.ndarray)
        or image.dtype != np.uint8
        or image.ndim != 3
        or image.shape[2] not in (3, 4)
    ):
        raise ValueError("player color sampling requires RGB/RGBA uint8 pixels")
    left, top, width, height = bounds
    if any(isinstance(value, bool) or not isinstance(value, int) for value in bounds):
        raise ValueError("sample bounds must be integers")
    if width <= 0 or height <= 0 or left < 0 or top < 0:
        raise ValueError("sample bounds must be positive and within the approved frame")
    if left + width > image.shape[1] or top + height > image.shape[0]:
        raise ValueError("sample bounds exceed the approved frame")
    patch = image[top : top + height, left : left + width, :3]
    # Bright, saturated pixels suppress most background/outline pixels.  The
    # median avoids a particle or one decorative pixel selecting the signature.
    saturation = patch.max(axis=2).astype(np.int16) - patch.min(axis=2).astype(np.int16)
    selected = patch[(saturation >= 40) & (patch.max(axis=2) >= 80)]
    if len(selected) < 4:
        raise ValueError("sample patch has too few saturated player-color pixels")
    median = np.median(selected, axis=0).round().astype(np.uint8)
    return (int(median[0]), int(median[1]), int(median[2]))


def _write_local(
    region: CaptureRegion,
    target_fps: int,
    backend: str,
    cube_color: tuple[int, int, int] | None,
) -> None:
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
        f"backend = \"{backend}\"\n"
    )
    if cube_color is not None:
        content += (
            "\n[vision]\n"
            f"cube_color = [{cube_color[0]}, {cube_color[1]}, {cube_color[2]}]\n"
        )
    payload = content.encode("utf-8")
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
        0o600,
    )
    try:
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("calibration configuration write did not complete")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    raise SystemExit(main())
