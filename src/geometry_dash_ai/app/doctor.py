"""Read-only environment diagnostics with sanitized output."""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from geometry_dash_ai.config.settings import ConfigError, load_config
from geometry_dash_ai.learning.calibration import CalibrationInvalid, CalibrationStore
from geometry_dash_ai.portal_transport import low_level_portal_ping


class CheckLevel(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    level: CheckLevel
    detail: str


def run_doctor(project_root: Path) -> tuple[DoctorCheck, ...]:
    """Perform no permission prompts and make no host changes."""
    root = project_root.resolve()
    checks: list[DoctorCheck] = []
    checks.append(
        DoctorCheck(
            "Python",
            CheckLevel.PASS if sys.version_info >= (3, 11) else CheckLevel.FAIL,
            platform.python_version(),
        )
    )
    checks.append(
        DoctorCheck(
            "Virtual environment",
            CheckLevel.PASS if sys.prefix != sys.base_prefix else CheckLevel.WARN,
            "active" if sys.prefix != sys.base_prefix else "not detected",
        )
    )
    tkinter_available = (
        importlib.util.find_spec("tkinter") is not None
        and importlib.util.find_spec("_tkinter") is not None
    )
    checks.append(
        DoctorCheck(
            "Tk support",
            CheckLevel.PASS,
            "available but unused by the main loopback UI"
            if tkinter_available
            else "not installed; the main loopback UI does not require Tk",
        )
    )
    wayland = os.environ.get("XDG_SESSION_TYPE") == "wayland"
    kde = "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "")
    checks.append(
        DoctorCheck(
            "Desktop",
            CheckLevel.PASS if wayland and kde else CheckLevel.WARN,
            "KDE Wayland" if wayland and kde else "non-KDE-Wayland or unavailable",
        )
    )
    portal_signals = bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS"))
    portal_reachable = portal_signals and low_level_portal_ping()
    checks.append(
        DoctorCheck(
            "User portal",
            CheckLevel.PASS if portal_reachable else CheckLevel.WARN,
            "org.freedesktop.portal.Desktop reachable through low-level D-Bus"
            if portal_reachable
            else (
                "session bus is configured but portal Ping was unavailable"
                if portal_signals
                else "DBUS_SESSION_BUS_ADDRESS is missing"
            ),
        )
    )
    checks.append(
        DoctorCheck(
            "ScreenCast transport",
            CheckLevel.PASS
            if importlib.util.find_spec("dbus_next") is not None
            else CheckLevel.WARN,
            "low-level fixed D-Bus transport available; no XML introspection"
            if importlib.util.find_spec("dbus_next") is not None
            else "dbus-next is unavailable; install the repository live extra in .venv",
        )
    )
    gst = shutil.which("gst-launch-1.0") is not None and _pipewire_plugin_available()
    checks.append(
        DoctorCheck(
            "PipeWire reader",
            CheckLevel.PASS if gst else CheckLevel.FAIL,
            "GStreamer PipeWire source available"
            if gst
            else "existing GStreamer PipeWire reader unavailable",
        )
    )
    for module in ("numpy", "dbus_next"):
        available = importlib.util.find_spec(module) is not None
        checks.append(
            DoctorCheck(
                f"Python module {module}",
                CheckLevel.PASS if available else CheckLevel.WARN,
                "available" if available else "install the repository live extra in .venv",
            )
        )
    control_available = portal_reachable and importlib.util.find_spec("dbus_next") is not None
    checks.append(
        DoctorCheck(
            "RemoteDesktop control",
            CheckLevel.PASS if control_available else CheckLevel.WARN,
            "keyboard-only low-level portal backend available; permission not requested by doctor"
            if control_available
            else "user-session bus or dbus-next unavailable; Observe remains usable",
        )
    )
    try:
        load_config(root / "config" / "default.toml", root / "config" / "local.toml")
        checks.append(DoctorCheck("Configuration", CheckLevel.PASS, "schema valid"))
    except ConfigError as exc:
        checks.append(DoctorCheck("Configuration", CheckLevel.FAIL, str(exc)))
    data = root / "data"
    checks.append(
        DoctorCheck(
            "Local data",
            CheckLevel.PASS if os.access(root, os.W_OK) else CheckLevel.FAIL,
            str(data.relative_to(root)),
        )
    )
    try:
        calibration = CalibrationStore(root)
        if calibration.path.exists():
            calibration.load()
            checks.append(DoctorCheck("Physics calibration", CheckLevel.PASS, "valid"))
        else:
            checks.append(DoctorCheck("Physics calibration", CheckLevel.WARN, "not collected yet"))
    except CalibrationInvalid as exc:
        checks.append(DoctorCheck("Physics calibration", CheckLevel.WARN, str(exc)))
    return tuple(checks)


def _pipewire_plugin_available() -> bool:
    executable = shutil.which("gst-inspect-1.0")
    if executable is None:
        return False
    try:
        result = subprocess.run(
            [executable, "pipewiresrc"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
