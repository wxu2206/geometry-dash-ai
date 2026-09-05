"""Load and validate user-editable TOML settings."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when configuration is missing, malformed, or unsafe."""


@dataclass(frozen=True, slots=True)
class CaptureConfig:
    left: int = 0
    top: int = 0
    width: int = 1280
    height: int = 720
    target_fps: int = 60
    backend: str = "portal"
    monitor: int | None = None
    preview_scale: float = 1.0
    diagnostic_mode: bool = False
    latest_frame_capacity: int = 1


@dataclass(frozen=True, slots=True)
class ControlConfig:
    enabled: bool = False
    emergency_stop_key: str = "f12"
    pause_key: str = "f10"
    manual_override: bool = True
    action_interval_ms: float = 16.667


@dataclass(frozen=True, slots=True)
class VisualizationConfig:
    enabled: bool = True
    show_alternatives: bool = True
    show_confidence: bool = True


@dataclass(frozen=True, slots=True)
class RecordingConfig:
    enabled: bool = False
    sample_every_n_frames: int = 30
    recent_buffer_seconds: float = 5.0
    preserve_death_context_seconds: float = 3.0
    compress_telemetry: bool = True
    maximum_recent_frames: int = 180


@dataclass(frozen=True, slots=True)
class VisionConfig:
    player_min_pixels: int = 16
    player_max_pixels: int = 10_000
    color_tolerance: int = 72
    mode_history_frames: int = 5
    tracker_max_missing_seconds: float = 0.5
    maximum_velocity_px_s: float = 5_000.0
    geometry_min_area_px: int = 16
    geometry_cache_frames: int = 12
    minimum_confidence: float = 0.35
    cube_color: tuple[int, int, int] = (255, 60, 200)
    ship_color: tuple[int, int, int] = (20, 230, 255)


@dataclass(frozen=True, slots=True)
class CalibrationConfig:
    enabled: bool = False
    minimum_observations: int = 30
    learning_rate: float = 0.05


@dataclass(frozen=True, slots=True)
class PlanningConfig:
    horizon_seconds: float = 1.25
    safety_margin_px: float = 6.0
    uncertainty_weight: float = 1.0
    maximum_jump_delay_frames: int = 24
    delay_increment_frames: int = 2
    maximum_candidates: int = 16
    maximum_obstacles: int = 128
    robustness_window_frames: int = 1


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    level: str = "INFO"
    directory: Path = Path("data/runs")


@dataclass(frozen=True, slots=True)
class AppConfig:
    capture: CaptureConfig = CaptureConfig()
    control: ControlConfig = ControlConfig()
    visualization: VisualizationConfig = VisualizationConfig()
    recording: RecordingConfig = RecordingConfig()
    vision: VisionConfig = VisionConfig()
    calibration: CalibrationConfig = CalibrationConfig()
    planning: PlanningConfig = PlanningConfig()
    logging: LoggingConfig = LoggingConfig()


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a TOML table")
    return value


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            parsed = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"could not load configuration {path}: {exc}") from exc
    return parsed


def _reject_unknown(section: str, values: dict[str, Any], allowed: set[str]) -> None:
    unknown = set(values) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ConfigError(f"unknown setting(s) in [{section}]: {names}")


def config_from_dict(data: dict[str, Any]) -> AppConfig:
    """Construct a validated configuration from decoded TOML data."""
    known_sections = {
        "calibration",
        "capture",
        "control",
        "logging",
        "planning",
        "recording",
        "vision",
        "visualization",
    }
    unknown_sections = set(data) - known_sections
    if unknown_sections:
        names = ", ".join(sorted(unknown_sections))
        raise ConfigError(f"unknown configuration section(s): {names}")

    capture = _section(data, "capture")
    control = _section(data, "control")
    visualization = _section(data, "visualization")
    recording = _section(data, "recording")
    vision = _section(data, "vision")
    vision_data = dict(vision)
    for color_name in ("cube_color", "ship_color"):
        if color_name in vision_data and isinstance(vision_data[color_name], list):
            vision_data[color_name] = tuple(vision_data[color_name])
    calibration = _section(data, "calibration")
    planning = _section(data, "planning")
    logging_data = _section(data, "logging")

    _reject_unknown(
        "capture",
        capture,
        {
            "left",
            "top",
            "width",
            "height",
            "target_fps",
            "backend",
            "monitor",
            "preview_scale",
            "diagnostic_mode",
            "latest_frame_capacity",
        },
    )
    _reject_unknown(
        "control",
        control,
        {"enabled", "emergency_stop_key", "pause_key", "manual_override", "action_interval_ms"},
    )
    _reject_unknown(
        "visualization", visualization, {"enabled", "show_alternatives", "show_confidence"}
    )
    _reject_unknown(
        "recording",
        recording,
        {
            "enabled",
            "sample_every_n_frames",
            "recent_buffer_seconds",
            "preserve_death_context_seconds",
            "compress_telemetry",
            "maximum_recent_frames",
        },
    )
    _reject_unknown(
        "vision",
        vision,
        {
            "player_min_pixels",
            "player_max_pixels",
            "color_tolerance",
            "mode_history_frames",
            "tracker_max_missing_seconds",
            "maximum_velocity_px_s",
            "geometry_min_area_px",
            "geometry_cache_frames",
            "minimum_confidence",
            "cube_color",
            "ship_color",
        },
    )
    _reject_unknown(
        "calibration", calibration, {"enabled", "minimum_observations", "learning_rate"}
    )
    _reject_unknown(
        "planning",
        planning,
        {
            "horizon_seconds",
            "safety_margin_px",
            "uncertainty_weight",
            "maximum_jump_delay_frames",
            "delay_increment_frames",
            "maximum_candidates",
            "maximum_obstacles",
            "robustness_window_frames",
        },
    )
    _reject_unknown("logging", logging_data, {"level", "directory"})

    try:
        result = AppConfig(
            capture=CaptureConfig(**capture),
            control=ControlConfig(**control),
            visualization=VisualizationConfig(**visualization),
            recording=RecordingConfig(**recording),
            vision=VisionConfig(**vision_data),
            calibration=CalibrationConfig(**calibration),
            planning=PlanningConfig(**planning),
            logging=LoggingConfig(
                level=logging_data.get("level", "INFO"),
                directory=Path(logging_data.get("directory", "data/runs")),
            ),
        )
    except TypeError as exc:
        raise ConfigError(f"invalid configuration value: {exc}") from exc
    _validate(result)
    return result


def _validate(config: AppConfig) -> None:
    integer_values = {
        "capture.left": config.capture.left,
        "capture.top": config.capture.top,
        "capture.width": config.capture.width,
        "capture.height": config.capture.height,
        "capture.target_fps": config.capture.target_fps,
        "capture.latest_frame_capacity": config.capture.latest_frame_capacity,
        "recording.sample_every_n_frames": config.recording.sample_every_n_frames,
        "recording.maximum_recent_frames": config.recording.maximum_recent_frames,
        "calibration.minimum_observations": config.calibration.minimum_observations,
        "vision.player_min_pixels": config.vision.player_min_pixels,
        "vision.player_max_pixels": config.vision.player_max_pixels,
        "vision.color_tolerance": config.vision.color_tolerance,
        "vision.mode_history_frames": config.vision.mode_history_frames,
        "vision.geometry_min_area_px": config.vision.geometry_min_area_px,
        "vision.geometry_cache_frames": config.vision.geometry_cache_frames,
    }
    value: object
    for name, value in integer_values.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{name} must be an integer")
        if abs(value) > 1_000_000_000:
            raise ConfigError(f"{name} exceeds supported bounds")
    boolean_values = {
        "control.enabled": config.control.enabled,
        "control.manual_override": config.control.manual_override,
        "visualization.enabled": config.visualization.enabled,
        "visualization.show_alternatives": config.visualization.show_alternatives,
        "visualization.show_confidence": config.visualization.show_confidence,
        "recording.enabled": config.recording.enabled,
        "recording.compress_telemetry": config.recording.compress_telemetry,
        "calibration.enabled": config.calibration.enabled,
    }
    for name, value in boolean_values.items():
        if not isinstance(value, bool):
            raise ConfigError(f"{name} must be a boolean")
    positive_values = {
        "capture.width": config.capture.width,
        "capture.height": config.capture.height,
        "capture.target_fps": config.capture.target_fps,
        "control.action_interval_ms": config.control.action_interval_ms,
        "recording.sample_every_n_frames": config.recording.sample_every_n_frames,
        "recording.recent_buffer_seconds": config.recording.recent_buffer_seconds,
        "recording.preserve_death_context_seconds": config.recording.preserve_death_context_seconds,
        "calibration.minimum_observations": config.calibration.minimum_observations,
        "planning.horizon_seconds": config.planning.horizon_seconds,
        "capture.preview_scale": config.capture.preview_scale,
        "vision.tracker_max_missing_seconds": config.vision.tracker_max_missing_seconds,
        "vision.maximum_velocity_px_s": config.vision.maximum_velocity_px_s,
        "vision.minimum_confidence": config.vision.minimum_confidence,
    }
    for name, value in positive_values.items():
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or abs(value) > 1_000_000_000
            or not isfinite(value)
            or value <= 0
        ):
            raise ConfigError(f"{name} must be a positive finite number")
    bounded_floats = {
        "calibration.learning_rate": (config.calibration.learning_rate, 0.0, 1.0),
        "planning.safety_margin_px": (config.planning.safety_margin_px, 0.0, 1_000_000.0),
        "planning.uncertainty_weight": (
            config.planning.uncertainty_weight,
            0.0,
            1_000_000.0,
        ),
    }
    for name, (value, minimum, maximum) in bounded_floats.items():
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or abs(value) > 1_000_000_000
            or not isfinite(value)
            or not minimum <= value <= maximum
        ):
            raise ConfigError(f"{name} must be finite and in [{minimum}, {maximum}]")
    if config.calibration.learning_rate == 0:
        raise ConfigError("calibration.learning_rate must be in (0, 1]")
    if not 1 <= config.capture.width <= 7_680 or not 1 <= config.capture.height <= 4_320:
        raise ConfigError("capture dimensions must be within 1..7680 by 1..4320")
    if not 1 <= config.capture.target_fps <= 240:
        raise ConfigError("capture.target_fps must be within 1..240")
    if not 1 <= config.capture.latest_frame_capacity <= 4:
        raise ConfigError("capture.latest_frame_capacity must be within 1..4")
    if not 1 <= config.recording.maximum_recent_frames <= 2_000:
        raise ConfigError("recording.maximum_recent_frames must be within 1..2000")
    if not 1 <= config.vision.player_min_pixels <= config.vision.player_max_pixels <= 100_000:
        raise ConfigError("vision player pixel limits are invalid")
    if not 1 <= config.vision.color_tolerance <= 255:
        raise ConfigError("vision.color_tolerance must be within 1..255")
    if not 1 <= config.vision.mode_history_frames <= 30:
        raise ConfigError("vision.mode_history_frames must be within 1..30")
    if not 1 <= config.vision.geometry_min_area_px <= 10_000:
        raise ConfigError("vision.geometry_min_area_px must be within 1..10000")
    if not 1 <= config.vision.geometry_cache_frames <= 120:
        raise ConfigError("vision.geometry_cache_frames must be within 1..120")
    if not 0.0 <= config.vision.minimum_confidence <= 1.0:
        raise ConfigError("vision.minimum_confidence must be within [0, 1]")
    if abs(config.capture.left) > 100_000 or abs(config.capture.top) > 100_000:
        raise ConfigError("capture origin exceeds supported bounds")
    if not 0.1 <= config.capture.preview_scale <= 4.0:
        raise ConfigError("capture.preview_scale must be within [0.1, 4]")
    if config.vision.tracker_max_missing_seconds > 10.0:
        raise ConfigError("vision.tracker_max_missing_seconds must be at most 10")
    if config.vision.maximum_velocity_px_s > 100_000.0:
        raise ConfigError("vision.maximum_velocity_px_s must be at most 100000")
    for name, color in (
        ("cube_color", config.vision.cube_color),
        ("ship_color", config.vision.ship_color),
    ):
        if (
            not isinstance(color, tuple)
            or len(color) != 3
            or any(
                isinstance(channel, bool)
                or not isinstance(channel, int)
                or not 0 <= channel <= 255
                for channel in color
            )
        ):
            raise ConfigError(f"vision.{name} must be three integer RGB channels")
    if not isinstance(config.capture.backend, str) or config.capture.backend not in {
        "mss",
        "synthetic",
        "portal",
    }:
        raise ConfigError("capture.backend must be 'portal', 'mss', or 'synthetic'")
    if config.capture.monitor is not None and (
        isinstance(config.capture.monitor, bool)
        or not isinstance(config.capture.monitor, int)
        or not 0 <= config.capture.monitor <= 64
    ):
        raise ConfigError("capture.monitor must be null or an integer within 0..64")
    if not isinstance(config.capture.diagnostic_mode, bool):
        raise ConfigError("capture.diagnostic_mode must be a boolean")
    bounded_integers = {
        "planning.maximum_jump_delay_frames": (
            config.planning.maximum_jump_delay_frames,
            3,
            240,
        ),
        "planning.delay_increment_frames": (config.planning.delay_increment_frames, 1, 240),
        "planning.maximum_candidates": (config.planning.maximum_candidates, 5, 64),
        "planning.maximum_obstacles": (config.planning.maximum_obstacles, 1, 256),
        "planning.robustness_window_frames": (
            config.planning.robustness_window_frames,
            0,
            3,
        ),
    }
    for name, (value, minimum, maximum) in bounded_integers.items():
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ConfigError(f"{name} must be an integer in [{minimum}, {maximum}]")
    control_keys = {
        "control.emergency_stop_key": config.control.emergency_stop_key,
        "control.pause_key": config.control.pause_key,
    }
    for name, value in control_keys.items():
        if not isinstance(value, str) or not value.strip() or len(value) > 64:
            raise ConfigError(f"{name} must be a non-empty string of at most 64 characters")
    if not isinstance(config.logging.level, str) or config.logging.level.upper() not in {
        "CRITICAL",
        "DEBUG",
        "ERROR",
        "INFO",
        "WARNING",
    }:
        raise ConfigError("logging.level is invalid")


def load_config(default_path: Path, local_path: Path | None = None) -> AppConfig:
    """Load defaults and an optional machine-local override."""
    data = _read_toml(default_path)
    if local_path is not None and local_path.exists():
        data = _merge(data, _read_toml(local_path))
    return config_from_dict(data)
