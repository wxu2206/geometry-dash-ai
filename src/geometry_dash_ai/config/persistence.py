"""Safe fixed-path persistence for validated local application settings."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from geometry_dash_ai.config.settings import AppConfig, config_from_dict


def save_local_config(project_root: Path, config: AppConfig) -> Path:
    """Save known typed fields to ``config/local.toml`` with owner-only access."""
    root = project_root.resolve()
    directory = (root / "config").resolve()
    if root not in directory.parents or directory.is_symlink():
        raise ValueError("refusing an unsafe local configuration directory")
    destination = directory / "local.toml"
    if destination.is_symlink():
        raise ValueError("refusing to write local configuration through a symlink")
    validated = config_from_dict(asdict(config))
    payload = _toml(validated).encode("utf-8")
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
                raise OSError("local configuration write did not complete")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return destination


def _toml(config: AppConfig) -> str:
    capture = config.capture
    control = config.control
    vision = config.vision
    recording = config.recording
    planning = config.planning
    monitor = "" if capture.monitor is None else f"monitor = {capture.monitor}\n"
    return (
        f"schema_version = {config.schema_version}\n\n"
        "[capture]\n"
        f"left = {capture.left}\n"
        f"top = {capture.top}\n"
        f"width = {capture.width}\n"
        f"height = {capture.height}\n"
        f"target_fps = {capture.target_fps}\n"
        f"backend = {_quote(capture.backend)}\n"
        f"{monitor}"
        f"preview_scale = {capture.preview_scale}\n"
        f"diagnostic_mode = {_boolean(capture.diagnostic_mode)}\n"
        f"latest_frame_capacity = {capture.latest_frame_capacity}\n\n"
        "[control]\n"
        f"enabled = {_boolean(control.enabled)}\n"
        f"emergency_stop_key = {_quote(control.emergency_stop_key)}\n"
        f"pause_key = {_quote(control.pause_key)}\n"
        f"manual_override = {_boolean(control.manual_override)}\n"
        f"action_interval_ms = {control.action_interval_ms}\n"
        f"backend = {_quote(control.backend)}\n"
        f"action_key = {_quote(control.action_key)}\n"
        f"tap_duration_ms = {control.tap_duration_ms}\n"
        f"maximum_hold_ms = {control.maximum_hold_ms}\n"
        f"maximum_actions_per_second = {control.maximum_actions_per_second}\n"
        f"heartbeat_timeout_ms = {control.heartbeat_timeout_ms}\n"
        f"maximum_session_seconds = {control.maximum_session_seconds}\n"
        f"arming_timeout_seconds = {control.arming_timeout_seconds}\n"
        f"maximum_attempts = {control.maximum_attempts}\n"
        f"auto_retry = {_boolean(control.auto_retry)}\n"
        f"retry_cooldown_seconds = {control.retry_cooldown_seconds}\n\n"
        "[visualization]\n"
        f"enabled = {_boolean(config.visualization.enabled)}\n"
        f"show_alternatives = {_boolean(config.visualization.show_alternatives)}\n"
        f"show_confidence = {_boolean(config.visualization.show_confidence)}\n\n"
        "[recording]\n"
        f"enabled = {_boolean(recording.enabled)}\n"
        f"sample_every_n_frames = {recording.sample_every_n_frames}\n"
        f"recent_buffer_seconds = {recording.recent_buffer_seconds}\n"
        f"preserve_death_context_seconds = {recording.preserve_death_context_seconds}\n"
        f"compress_telemetry = {_boolean(recording.compress_telemetry)}\n"
        f"maximum_recent_frames = {recording.maximum_recent_frames}\n\n"
        "[vision]\n"
        f"player_min_pixels = {vision.player_min_pixels}\n"
        f"player_max_pixels = {vision.player_max_pixels}\n"
        f"color_tolerance = {vision.color_tolerance}\n"
        f"mode_history_frames = {vision.mode_history_frames}\n"
        f"tracker_max_missing_seconds = {vision.tracker_max_missing_seconds}\n"
        f"maximum_velocity_px_s = {vision.maximum_velocity_px_s}\n"
        f"geometry_min_area_px = {vision.geometry_min_area_px}\n"
        f"geometry_cache_frames = {vision.geometry_cache_frames}\n"
        f"minimum_confidence = {vision.minimum_confidence}\n"
        f"cube_color = {list(vision.cube_color)}\n"
        f"ship_color = {list(vision.ship_color)}\n\n"
        "[calibration]\n"
        f"enabled = {_boolean(config.calibration.enabled)}\n"
        f"minimum_observations = {config.calibration.minimum_observations}\n"
        f"learning_rate = {config.calibration.learning_rate}\n\n"
        "[planning]\n"
        f"horizon_seconds = {planning.horizon_seconds}\n"
        f"safety_margin_px = {planning.safety_margin_px}\n"
        f"uncertainty_weight = {planning.uncertainty_weight}\n"
        f"maximum_jump_delay_frames = {planning.maximum_jump_delay_frames}\n"
        f"delay_increment_frames = {planning.delay_increment_frames}\n"
        f"maximum_candidates = {planning.maximum_candidates}\n"
        f"maximum_obstacles = {planning.maximum_obstacles}\n"
        f"robustness_window_frames = {planning.robustness_window_frames}\n\n"
        "[logging]\n"
        f"level = {_quote(config.logging.level)}\n"
        f"directory = {_quote(config.logging.directory.as_posix())}\n"
    )


def _quote(value: str) -> str:
    return json.dumps(value)


def _boolean(value: bool) -> str:
    return "true" if value else "false"
