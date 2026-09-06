"""Bounded visual cube-physics fitting and versioned local persistence."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from math import isfinite
from pathlib import Path

import numpy as np

CALIBRATION_SCHEMA_VERSION = 1


class CalibrationInvalid(ValueError):
    """Calibration samples or stored parameters failed validation."""


@dataclass(frozen=True, slots=True)
class AirborneSample:
    time_seconds: float
    y: float
    confidence: float

    def __post_init__(self) -> None:
        values = (self.time_seconds, self.y, self.confidence)
        if not all(isinstance(value, (int, float)) and isfinite(value) for value in values):
            raise CalibrationInvalid("airborne calibration sample must be finite")
        if self.time_seconds < 0.0 or not 0.0 <= self.confidence <= 1.0:
            raise CalibrationInvalid("airborne calibration sample is outside bounds")


@dataclass(frozen=True, slots=True)
class PhysicsCalibration:
    schema_version: int = CALIBRATION_SCHEMA_VERSION
    gravity: float = -1_300.0
    jump_velocity: float = 480.0
    horizontal_speed: float = 180.0
    collision_width: float = 24.0
    collision_height: float = 24.0
    action_latency_seconds: float = 0.04
    detection_latency_seconds: float = 0.02
    uncertainty: float = 0.5
    sample_count: int = 0
    revision: int = 0

    def __post_init__(self) -> None:
        if self.schema_version != CALIBRATION_SCHEMA_VERSION:
            raise CalibrationInvalid("unsupported calibration schema")
        numeric = (
            self.gravity,
            self.jump_velocity,
            self.horizontal_speed,
            self.collision_width,
            self.collision_height,
            self.action_latency_seconds,
            self.detection_latency_seconds,
            self.uncertainty,
        )
        if not all(isinstance(value, (int, float)) and isfinite(value) for value in numeric):
            raise CalibrationInvalid("calibration values must be finite")
        if not -10_000.0 <= self.gravity <= -100.0 or not 50.0 <= self.jump_velocity <= 2_000.0:
            raise CalibrationInvalid("cube ballistic calibration is outside safe bounds")
        if not 20.0 <= self.horizontal_speed <= 2_000.0:
            raise CalibrationInvalid("horizontal speed is outside safe bounds")
        if not 4.0 <= self.collision_width <= 256.0 or not 4.0 <= self.collision_height <= 256.0:
            raise CalibrationInvalid("collision dimensions are outside safe bounds")
        if not 0.0 <= self.action_latency_seconds <= 0.5:
            raise CalibrationInvalid("action latency is outside safe bounds")
        if not 0.0 <= self.detection_latency_seconds <= 0.5:
            raise CalibrationInvalid("detection latency is outside safe bounds")
        if not 0.0 <= self.uncertainty <= 1.0:
            raise CalibrationInvalid("calibration uncertainty is outside bounds")
        if not 0 <= self.sample_count <= 1_000_000 or not 0 <= self.revision <= 1_000_000:
            raise CalibrationInvalid("calibration counters are outside bounds")


class CubePhysicsCalibrator:
    """Fit robust ballistic trajectories and retain a reversible known-good model."""

    def __init__(self, minimum_samples: int = 12, learning_rate: float = 0.05) -> None:
        if not 6 <= minimum_samples <= 1_000 or not 0.001 <= learning_rate <= 0.25:
            raise ValueError("calibrator limits are invalid")
        self._minimum_samples = minimum_samples
        self._learning_rate = learning_rate
        self.current = PhysicsCalibration()
        self.last_known_good = self.current

    def fit_airborne(self, samples: tuple[AirborneSample, ...]) -> PhysicsCalibration:
        usable = tuple(sample for sample in samples if sample.confidence >= 0.5)
        if len(usable) < self._minimum_samples:
            raise CalibrationInvalid("insufficient high-confidence airborne samples")
        times = np.asarray([sample.time_seconds for sample in usable], dtype=np.float64)
        positions = np.asarray([sample.y for sample in usable], dtype=np.float64)
        if float(times.max() - times.min()) < 0.1:
            raise CalibrationInvalid("airborne samples cover too little time")
        design = np.column_stack((np.ones_like(times), times, times * times))
        coefficients, _, _, _ = np.linalg.lstsq(design, positions, rcond=None)
        residuals = positions - design @ coefficients
        median = float(np.median(residuals))
        mad = float(np.median(np.abs(residuals - median)))
        keep = np.abs(residuals - median) <= max(1.0, mad * 4.5)
        if int(keep.sum()) < self._minimum_samples:
            raise CalibrationInvalid("too many airborne samples were outliers")
        coefficients, _, _, _ = np.linalg.lstsq(design[keep], positions[keep], rcond=None)
        fitted = replace(
            self.current,
            gravity=float(2.0 * coefficients[2]),
            jump_velocity=float(coefficients[1]),
            uncertainty=min(1.0, max(0.02, mad / 20.0)),
            sample_count=int(keep.sum()),
            revision=self.current.revision + 1,
        )
        self.current = fitted
        return fitted

    def adapt(self, candidate: PhysicsCalibration, observed_error_px: float) -> PhysicsCalibration:
        if not isfinite(observed_error_px) or observed_error_px < 0.0:
            raise CalibrationInvalid("observed calibration error is invalid")
        if observed_error_px > 96.0:
            self.current = self.last_known_good
            return self.current
        rate = self._learning_rate
        blended = replace(
            self.current,
            gravity=self.current.gravity * (1.0 - rate) + candidate.gravity * rate,
            jump_velocity=(
                self.current.jump_velocity * (1.0 - rate) + candidate.jump_velocity * rate
            ),
            action_latency_seconds=(
                self.current.action_latency_seconds * (1.0 - rate)
                + candidate.action_latency_seconds * rate
            ),
            uncertainty=min(1.0, max(0.01, observed_error_px / 48.0)),
            sample_count=max(self.current.sample_count, candidate.sample_count),
            revision=self.current.revision + 1,
        )
        self.current = blended
        if observed_error_px <= 8.0 and blended.sample_count >= self._minimum_samples:
            self.last_known_good = blended
        return blended


class CalibrationStore:
    """Read/write one validated JSON model below project-local data/calibration."""

    def __init__(self, project_root: Path) -> None:
        self._root = project_root.resolve()
        data = self._root / "data"
        directory = data / "calibration"
        if data.is_symlink() or directory.is_symlink():
            raise CalibrationInvalid("refusing a symlink calibration directory")
        self.path = directory / "physics.json"
        if self._root not in self.path.parents:
            raise CalibrationInvalid("calibration path escapes the project data directory")

    def save(self, current: PhysicsCalibration, known_good: PhysicsCalibration) -> None:
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise CalibrationInvalid("refusing to write calibration through a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "schema_version": CALIBRATION_SCHEMA_VERSION,
                "current": asdict(current),
                "last_known_good": asdict(known_good),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        descriptor = os.open(
            self.path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
            0o600,
        )
        try:
            remaining = memoryview(payload)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise CalibrationInvalid("could not complete calibration write")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def load(self) -> tuple[PhysicsCalibration, PhysicsCalibration]:
        try:
            decoded = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(decoded, dict)
                or decoded.get("schema_version") != CALIBRATION_SCHEMA_VERSION
            ):
                raise CalibrationInvalid("calibration file schema is invalid")
            current = decoded.get("current")
            known_good = decoded.get("last_known_good")
            if not isinstance(current, dict) or not isinstance(known_good, dict):
                raise CalibrationInvalid("calibration file content is invalid")
            return PhysicsCalibration(**current), PhysicsCalibration(**known_good)
        except (OSError, json.JSONDecodeError, TypeError, CalibrationInvalid) as exc:
            raise CalibrationInvalid(f"could not load calibration safely: {exc}") from exc
