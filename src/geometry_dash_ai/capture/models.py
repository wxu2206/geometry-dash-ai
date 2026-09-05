"""Validated, bounded screen-capture data models.

Frames are RGB/RGBA ``numpy.uint8`` arrays in image coordinates: origin at the
top-left, x rightward, y downward. A frame is never copied by this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import Any, Final

import numpy as np

MAX_CAPTURE_WIDTH: Final = 7_680
MAX_CAPTURE_HEIGHT: Final = 4_320
MAX_CAPTURE_PIXELS: Final = MAX_CAPTURE_WIDTH * MAX_CAPTURE_HEIGHT
# NumPy's stub syntax changes faster than this project's supported Python floor.
# Runtime validation below is the authority at this external-data boundary.
RgbImage = Any


def _finite_int(name: str, value: object, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


@dataclass(frozen=True, slots=True)
class CaptureRegion:
    """The only desktop area a frame source is authorized to observe."""

    left: int
    top: int
    width: int
    height: int
    monitor: int | None = None

    def __post_init__(self) -> None:
        _finite_int("CaptureRegion.left", self.left, -100_000, 100_000)
        _finite_int("CaptureRegion.top", self.top, -100_000, 100_000)
        _finite_int("CaptureRegion.width", self.width, 1, MAX_CAPTURE_WIDTH)
        _finite_int("CaptureRegion.height", self.height, 1, MAX_CAPTURE_HEIGHT)
        if self.width * self.height > MAX_CAPTURE_PIXELS:
            raise ValueError("capture region exceeds supported pixel limit")
        if self.monitor is not None:
            _finite_int("CaptureRegion.monitor", self.monitor, 0, 64)

    @property
    def as_mapping(self) -> Mapping[str, int]:
        """Return immutable backend metadata without desktop/window details."""
        return MappingProxyType(
            {"left": self.left, "top": self.top, "width": self.width, "height": self.height}
        )


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    """A single validated image and its monotonic capture metadata."""

    image: RgbImage
    timestamp_ns: int
    sequence: int
    region: CaptureRegion

    def __post_init__(self) -> None:
        if not isinstance(self.region, CaptureRegion):
            raise ValueError("frame region is invalid")
        _finite_int("CapturedFrame.timestamp_ns", self.timestamp_ns, 0, 2**63 - 1)
        _finite_int("CapturedFrame.sequence", self.sequence, 0, 2**63 - 1)
        validate_image(
            self.image, expected_width=self.region.width, expected_height=self.region.height
        )

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])


def validate_image(
    image: object,
    *,
    expected_width: int | None = None,
    expected_height: int | None = None,
) -> None:
    """Reject malformed or oversized visual input before allocation-heavy work."""
    if not isinstance(image, np.ndarray):
        raise ValueError("frame image must be a numpy array")
    if image.dtype != np.uint8:
        raise ValueError("frame image must have uint8 pixels")
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError("frame image must have shape (height, width, 3|4)")
    height, width, channels = image.shape
    if height <= 0 or width <= 0 or channels not in (3, 4):
        raise ValueError("frame image dimensions must be positive")
    if (
        height > MAX_CAPTURE_HEIGHT
        or width > MAX_CAPTURE_WIDTH
        or height * width > MAX_CAPTURE_PIXELS
    ):
        raise ValueError("frame image exceeds supported capture size")
    if expected_width is not None and width != expected_width:
        raise ValueError("frame image width does not match capture region")
    if expected_height is not None and height != expected_height:
        raise ValueError("frame image height does not match capture region")
    if not image.flags.c_contiguous:
        raise ValueError("frame image must be contiguous")
    if image.nbytes != height * width * channels:
        raise ValueError("frame image has inconsistent storage")
    if image.dtype.kind == "f" and not np.isfinite(image).all():
        raise ValueError("frame image contains non-finite pixels")


def validate_rate(value: object) -> float:
    """Validate a configured or measured positive rate without NaN propagation."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("rate must be a finite positive number")
    rate = float(value)
    if not isfinite(rate) or not 0.0 < rate <= 10_000.0:
        raise ValueError("rate must be finite and within supported bounds")
    return rate
