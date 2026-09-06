"""Responsive Tk dashboard for setup, observation, shadow, and guarded live control."""

from __future__ import annotations

import base64
import threading
from collections import deque
from dataclasses import replace
from pathlib import Path
from time import monotonic, monotonic_ns
from typing import Any

import numpy as np

from geometry_dash_ai.app.doctor import run_doctor
from geometry_dash_ai.app.ipc import LocalRuntimeFiles
from geometry_dash_ai.app.state import AppState
from geometry_dash_ai.app.supervisor import RuntimeSupervisor, SupervisorLimits
from geometry_dash_ai.app.ui_model import buttons_for, prominent_status
from geometry_dash_ai.capture import (
    CaptureRegion,
    FrameSource,
    MssFrameSource,
    PipeWirePortalFrameSource,
    SyntheticFrameSource,
)
from geometry_dash_ai.config.persistence import save_local_config
from geometry_dash_ai.config.settings import AppConfig
from geometry_dash_ai.control import ControlLimits, KdeRemoteDesktopActionBackend
from geometry_dash_ai.learning import CalibrationStore, VisualCubeCalibrationCollector
from geometry_dash_ai.physics import CubePhysicsParameters
from geometry_dash_ai.planning import CubePlannerConfig
from geometry_dash_ai.telemetry import RunHistoryStore
from geometry_dash_ai.ui.overlay import render_debug_overlay
from geometry_dash_ai.ui.viewer import scale_preview
from geometry_dash_ai.vision.__main__ import build_pipeline
from geometry_dash_ai.vision.pipeline import PerceptionSnapshot
from geometry_dash_ai.vision.run_state import detect_completion_visual_cue


class AlphaUiUnavailable(RuntimeError):
    """Tk could not open in the current desktop session."""


class AlphaTkApplication:
    """Small engineering dashboard; capture/perception/planning run off the Tk thread."""

    def __init__(self, config: AppConfig, project_root: Path) -> None:
        try:
            import tkinter as tk
            from tkinter import messagebox

            self._tk = tk
            self._messagebox = messagebox
            self._root = tk.Tk()
        except Exception as exc:
            raise AlphaUiUnavailable("could not open the local Tk application window") from exc
        self._config = config
        self._project_root = project_root.resolve()
        setup_complete = (self._project_root / "config" / "local.toml").exists()
        calibration_store = CalibrationStore(self._project_root)
        self._calibration = VisualCubeCalibrationCollector(
            calibration_store,
            minimum_samples=config.calibration.minimum_observations,
            learning_rate=config.calibration.learning_rate,
        )
        self._calibration_enabled = config.calibration.enabled
        self._supervisor = RuntimeSupervisor(
            setup_complete=setup_complete,
            limits=SupervisorLimits(
                maximum_attempts=config.control.maximum_attempts,
                retry_cooldown_seconds=config.control.retry_cooldown_seconds,
            ),
            run_history=RunHistoryStore(self._project_root),
            physics_ready=self._calibration.ready,
            cube_physics=CubePhysicsParameters(
                gravity=self._calibration.current.gravity,
                jump_velocity=self._calibration.current.jump_velocity,
                horizontal_speed=self._calibration.current.horizontal_speed,
                collision_width=self._calibration.current.collision_width,
                collision_height=self._calibration.current.collision_height,
            ),
            cube_planner=CubePlannerConfig(
                horizon_seconds=config.planning.horizon_seconds,
                maximum_jump_delay_frames=config.planning.maximum_jump_delay_frames,
                delay_increment_frames=config.planning.delay_increment_frames,
                maximum_candidates=config.planning.maximum_candidates,
                maximum_obstacles=config.planning.maximum_obstacles,
                robustness_window_frames=config.planning.robustness_window_frames,
                uncertainty_weight=min(1_000.0, config.planning.uncertainty_weight * 400.0),
            ),
            action_latency_seconds=self._calibration.current.action_latency_seconds,
        )
        self._supervisor_lock = threading.RLock()
        self._runtime_files = LocalRuntimeFiles()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._source: FrameSource | None = None
        self._latest: deque[tuple[PerceptionSnapshot, Any]] = deque(maxlen=1)
        self._latest_lock = threading.Lock()
        self._last_snapshot: PerceptionSnapshot | None = None
        self._photo: Any | None = None
        self._buttons: dict[str, Any] = {}
        self._status_variables: dict[str, Any] = {}
        self._live_enabled = tk.BooleanVar(value=False)
        self._build()

    def _build(self) -> None:
        tk = self._tk
        self._root.title("Geometry Dash AI 0.2.0 alpha")
        self._root.geometry("1040x760")
        self._root.protocol("WM_DELETE_WINDOW", self._shutdown)
        title = tk.Label(self._root, text="GEOMETRY DASH AI", font=("TkDefaultFont", 18, "bold"))
        title.pack(pady=(10, 2))
        self._banner = tk.Label(
            self._root,
            text="STARTING",
            font=("TkDefaultFont", 14, "bold"),
            bg="#374151",
            fg="white",
            padx=20,
            pady=8,
        )
        self._banner.pack(fill="x", padx=12)
        body = tk.Frame(self._root)
        body.pack(fill="both", expand=True, padx=12, pady=8)
        dashboard = tk.LabelFrame(body, text="Dashboard", padx=8, pady=8)
        dashboard.pack(side="left", fill="y")
        names = (
            "App status",
            "Capture",
            "Control",
            "Game mode",
            "Attempt",
            "Capture FPS",
            "Perception FPS",
            "Planner Hz",
            "Latency",
            "Player confidence",
            "Geometry confidence",
            "Planner confidence",
            "Physics calibration",
            "Dropped frames",
            "Recommendation",
            "Predicted risk",
            "Last error",
        )
        for row, name in enumerate(names):
            tk.Label(dashboard, text=f"{name}:", anchor="e", width=20).grid(row=row, column=0)
            variable = tk.StringVar(value="—")
            tk.Label(dashboard, textvariable=variable, anchor="w", width=28).grid(row=row, column=1)
            self._status_variables[name] = variable
        preview_frame = tk.LabelFrame(body, text="Validated local preview", padx=4, pady=4)
        preview_frame.pack(side="right", fill="both", expand=True, padx=(8, 0))
        self._preview = tk.Label(preview_frame, text="Start Observe to request capture")
        self._preview.pack(fill="both", expand=True)
        controls = tk.LabelFrame(self._root, text="Controls", padx=8, pady=8)
        controls.pack(fill="x", padx=12, pady=(0, 12))
        actions = (
            ("setup", "Setup", self._setup),
            ("reset", "Reset Local Data", self._reset_local),
            ("diagnostics", "Diagnostics", self._diagnostics),
            ("observe", "Start Observe", self._start_observe),
            ("shadow", "Start Shadow", self._enter_shadow),
            ("request_control", "Request Live Control", self._request_control),
            ("arm", "Arm AI", self._arm),
            ("start", "Start AI", self._start_ai),
            ("pause", "Pause", self._pause),
            ("resume", "Resume", self._resume),
        )
        for column, (key, label, command) in enumerate(actions):
            button = tk.Button(controls, text=label, command=command)
            button.grid(row=0, column=column, padx=2, pady=2)
            self._buttons[key] = button
        tk.Checkbutton(
            controls,
            text="I understand live control sends bounded Space-key events",
            variable=self._live_enabled,
        ).grid(row=1, column=0, columnspan=8, sticky="w", pady=(8, 0))
        emergency = tk.Button(
            controls,
            text="EMERGENCY STOP",
            command=self._emergency_stop,
            bg="#b91c1c",
            fg="white",
            font=("TkDefaultFont", 12, "bold"),
        )
        emergency.grid(row=1, column=8, columnspan=2, sticky="ew", padx=4, pady=(8, 0))
        self._buttons["emergency_stop"] = emergency
        self._poll()

    def _diagnostics(self) -> None:
        checks = run_doctor(self._project_root)
        worker = self._worker
        thread_status = "alive" if worker is not None and worker.is_alive() else "stopped"
        lines = [f"{check.level.value} {check.name}: {check.detail}" for check in checks]
        lines.append(f"INFO Capture worker: {thread_status}")
        report = "\n".join(lines)
        self._messagebox.showinfo("Sanitized diagnostics", report)

    def _reset_local(self) -> None:
        confirmed = self._messagebox.askyesno(
            "Reset local data",
            "Delete local settings, learned calibration, and run history?\n"
            "Captured diagnostic event files are intentionally left untouched.",
        )
        if not confirmed:
            return
        targets = (
            self._project_root / "config" / "local.toml",
            self._project_root / "data" / "calibration" / "physics.json",
            self._project_root / "data" / "runs" / "history.jsonl",
        )
        try:
            for target in targets:
                resolved_parent = target.parent.resolve()
                if (
                    self._project_root not in resolved_parent.parents
                    or target.is_symlink()
                    or target.parent.is_symlink()
                ):
                    raise ValueError("refusing an unsafe reset target")
                target.unlink(missing_ok=True)
            self._messagebox.showinfo(
                "Local data reset",
                "Local settings, calibration, and run history were removed. Restart the app.",
            )
        except (OSError, ValueError) as exc:
            self._messagebox.showerror("Reset failed", str(exc))

    def run(self) -> None:
        self._root.mainloop()

    def _setup(self) -> None:
        tk = self._tk
        dialog = tk.Toplevel(self._root)
        dialog.title("First-run setup")
        dialog.transient(self._root)
        dialog.grab_set()
        description = (
            "Launch Geometry Dash and open Stereo Madness. Enter a crop relative to the "
            "portal-selected window/monitor. Start Observe afterward to approve KDE capture."
        )
        tk.Label(dialog, text=description, wraplength=520, justify="left").grid(
            row=0, column=0, columnspan=2, padx=12, pady=10
        )
        fields = {
            "Crop left": str(self._config.capture.left),
            "Crop top": str(self._config.capture.top),
            "Crop width": str(self._config.capture.width),
            "Crop height": str(self._config.capture.height),
            "Target FPS": str(self._config.capture.target_fps),
            "Player color tolerance": str(self._config.vision.color_tolerance),
            "Maximum attempts": str(self._config.control.maximum_attempts),
        }
        values: dict[str, Any] = {}
        for row, (label, initial) in enumerate(fields.items(), start=1):
            tk.Label(dialog, text=label, anchor="e").grid(row=row, column=0, sticky="e")
            variable = tk.StringVar(value=initial)
            tk.Entry(dialog, textvariable=variable, width=18).grid(
                row=row, column=1, sticky="w", padx=6, pady=2
            )
            values[label] = variable
        live = tk.BooleanVar(value=self._config.control.enabled)
        retry = tk.BooleanVar(value=self._config.control.auto_retry)
        recording = tk.BooleanVar(value=self._config.recording.enabled)
        calibration = tk.BooleanVar(value=self._config.calibration.enabled)
        row = len(fields) + 1
        tk.Checkbutton(dialog, text="Allow live-control workflow", variable=live).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=12
        )
        tk.Checkbutton(dialog, text="Auto retry (bounded)", variable=retry).grid(
            row=row + 1, column=0, columnspan=2, sticky="w", padx=12
        )
        tk.Checkbutton(
            dialog,
            text="Diagnostic event frames (local; off by default)",
            variable=recording,
        ).grid(row=row + 2, column=0, columnspan=2, sticky="w", padx=12)
        tk.Checkbutton(
            dialog,
            text="Learn cube physics from manual visual jumps",
            variable=calibration,
        ).grid(row=row + 3, column=0, columnspan=2, sticky="w", padx=12)

        def save() -> None:
            try:
                capture = replace(
                    self._config.capture,
                    left=int(values["Crop left"].get()),
                    top=int(values["Crop top"].get()),
                    width=int(values["Crop width"].get()),
                    height=int(values["Crop height"].get()),
                    target_fps=int(values["Target FPS"].get()),
                )
                vision = replace(
                    self._config.vision,
                    color_tolerance=int(values["Player color tolerance"].get()),
                )
                control = replace(
                    self._config.control,
                    enabled=bool(live.get()),
                    auto_retry=bool(retry.get()),
                    maximum_attempts=int(values["Maximum attempts"].get()),
                )
                candidate = replace(
                    self._config,
                    capture=capture,
                    vision=vision,
                    control=control,
                    recording=replace(self._config.recording, enabled=bool(recording.get())),
                    calibration=replace(
                        self._config.calibration,
                        enabled=bool(calibration.get()),
                    ),
                )
                save_local_config(self._project_root, candidate)
                self._config = candidate
                self._calibration_enabled = candidate.calibration.enabled
                if self._supervisor.state.state is AppState.SETUP_REQUIRED:
                    with self._supervisor_lock:
                        self._supervisor.setup_completed()
                dialog.destroy()
                self._messagebox.showinfo(
                    "Setup saved",
                    "Configuration saved locally. Start Observe to approve KDE capture. "
                    "Use 'geometry-dash-ai calibrate --sample-player …' when color sampling "
                    "is needed.",
                )
            except (OSError, TypeError, ValueError) as exc:
                self._messagebox.showerror("Invalid setup", str(exc))

        tk.Button(dialog, text="Save validated setup", command=save).grid(
            row=row + 4, column=0, columnspan=2, pady=12
        )

    def _start_observe(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop.clear()
        with self._supervisor_lock:
            self._supervisor.begin_capture()
        self._worker = threading.Thread(target=self._capture_worker, name="gdai-capture")
        self._worker.start()

    def _capture_worker(self) -> None:
        source: FrameSource | None = None
        try:
            source = self._make_source()
            self._source = source
            pipeline = build_pipeline(self._config)
            first = True
            interval = 1.0 / self._config.capture.target_fps
            while not self._stop.is_set():
                started = monotonic()
                frame = source.capture_once()
                snapshot = pipeline.process(frame)
                fitted = (
                    self._calibration.update(snapshot)
                    if self._calibration_enabled
                    else None
                )
                if first:
                    with self._supervisor_lock:
                        self._supervisor.capture_ready()
                    first = False
                with self._supervisor_lock:
                    if fitted is not None:
                        self._supervisor.set_cube_calibration(fitted)
                    self._supervisor.process(
                        snapshot, completion_visual_cue=detect_completion_visual_cue(frame)
                    )
                    if self._config.control.auto_retry:
                        self._supervisor.maybe_retry(monotonic_ns())
                    runtime_state = self._supervisor.state.state
                    if runtime_state in {AppState.SHADOW, AppState.ARMED, AppState.PAUSED}:
                        self._supervisor.plan_shadow(snapshot)
                    shadow = self._supervisor.cube_shadow
                    ship_shadow = self._supervisor.ship_shadow
                overlay = render_debug_overlay(
                    frame.image,
                    snapshot.tracked_player.bounds,
                    snapshot.fused_geometry,
                    shadow,
                    ship_shadow,
                )
                with self._latest_lock:
                    self._latest.append((snapshot, overlay))
                self._stop.wait(max(0.0, interval - (monotonic() - started)))
        except Exception as exc:
            with self._supervisor_lock:
                self._supervisor.degrade(f"capture/runtime stopped: {exc}")
        finally:
            if source is not None:
                source.close()
            self._source = None

    def _make_source(self) -> FrameSource:
        capture = self._config.capture
        region = CaptureRegion(
            capture.left,
            capture.top,
            capture.width,
            capture.height,
            capture.monitor,
        )
        if capture.backend == "portal":
            return PipeWirePortalFrameSource(region, capture.target_fps)
        if capture.backend == "mss":
            return MssFrameSource(region, capture.target_fps)
        image = np.zeros((region.height, region.width, 3), dtype=np.uint8)
        return SyntheticFrameSource(region, (image,))

    def _enter_shadow(self) -> None:
        with self._supervisor_lock:
            self._supervisor.enter_shadow()

    def _request_control(self) -> None:
        if not self._config.control.enabled:
            self._messagebox.showwarning(
                "Live control disabled",
                "Enable the live-control workflow in Setup before requesting KDE permission.",
            )
            return
        if not self._live_enabled.get():
            self._messagebox.showwarning(
                "Live control disabled", "Check the live-control acknowledgement first."
            )
            return
        try:
            self._runtime_files.acquire_control()
            backend = KdeRemoteDesktopActionBackend()
            control = self._config.control
            with self._supervisor_lock:
                self._supervisor.attach_control(
                    backend,
                    ControlLimits(
                        control.tap_duration_ms,
                        control.maximum_hold_ms,
                        control.maximum_actions_per_second,
                        control.heartbeat_timeout_ms,
                        control.maximum_session_seconds,
                        control.arming_timeout_seconds,
                    ),
                )
        except Exception as exc:
            self._runtime_files.release_control()
            self._messagebox.showerror("Live control unavailable", str(exc))

    def _arm(self) -> None:
        if self._last_snapshot is None:
            self._messagebox.showerror(
                "Cannot arm", "No validated perception snapshot is available."
            )
            return
        self._arm_countdown(3)

    def _arm_countdown(self, remaining: int) -> None:
        if remaining > 0:
            self._banner.configure(text=f"ARMING IN {remaining} — SHADOW ONLY", bg="#b45309")
            self._root.after(1_000, lambda: self._arm_countdown(remaining - 1))
            return
        try:
            if self._last_snapshot is None:
                raise RuntimeError("perception stopped during arming countdown")
            now = monotonic_ns()
            with self._supervisor_lock:
                readiness = self._supervisor.readiness(self._last_snapshot, now)
                self._supervisor.arm(now, readiness)
        except Exception as exc:
            self._messagebox.showerror("Cannot arm", str(exc))

    def _start_ai(self) -> None:
        try:
            with self._supervisor_lock:
                self._supervisor.start(monotonic_ns())
        except Exception as exc:
            self._messagebox.showerror("Cannot start", str(exc))

    def _pause(self) -> None:
        with self._supervisor_lock:
            self._supervisor.pause()

    def _resume(self) -> None:
        try:
            with self._supervisor_lock:
                self._supervisor.resume(monotonic_ns())
        except Exception as exc:
            self._messagebox.showerror("Cannot resume", str(exc))

    def _emergency_stop(self) -> None:
        self._stop.set()
        with self._supervisor_lock:
            self._supervisor.emergency_stop()
        self._runtime_files.release_control()

    def _poll(self) -> None:
        if self._runtime_files.consume_stop():
            self._emergency_stop()
        item: tuple[PerceptionSnapshot, Any] | None = None
        with self._latest_lock:
            if self._latest:
                item = self._latest.pop()
                self._latest.clear()
        if item is not None:
            self._last_snapshot, overlay = item
            self._show_image(overlay)
        self._update_dashboard()
        self._root.after(50, self._poll)

    def _show_image(self, image: Any) -> None:
        displayed = scale_preview(image, min(1.0, 600.0 / image.shape[1]))
        height, width, _ = displayed.shape
        ppm = f"P6 {width} {height} 255\n".encode("ascii") + displayed.tobytes()
        self._photo = self._tk.PhotoImage(data=base64.b64encode(ppm))
        self._preview.configure(image=self._photo, text="")

    def _update_dashboard(self) -> None:
        with self._supervisor_lock:
            dashboard = self._supervisor.dashboard(self._last_snapshot)
        capture_fps = self._source.capture_fps if self._source is not None else 0.0
        dropped_frames = self._source.dropped_frames if self._source is not None else 0
        values = {
            "App status": dashboard.status,
            "Capture": dashboard.capture_status,
            "Control": dashboard.control_status,
            "Game mode": dashboard.game_mode,
            "Attempt": str(dashboard.attempt),
            "Capture FPS": f"{capture_fps:.1f}",
            "Perception FPS": f"{dashboard.perception_fps:.1f}",
            "Planner Hz": f"{dashboard.planner_hz:.1f}",
            "Latency": f"{dashboard.latency_ms:.1f} ms",
            "Player confidence": f"{dashboard.player_confidence:.2f}",
            "Geometry confidence": f"{dashboard.geometry_confidence:.2f}",
            "Planner confidence": f"{dashboard.planner_confidence:.2f}",
            "Physics calibration": "ready" if dashboard.physics_ready else "collecting",
            "Dropped frames": str(dropped_frames),
            "Recommendation": dashboard.predicted_action,
            "Predicted risk": dashboard.risk,
            "Last error": dashboard.last_error or "—",
        }
        for name, value in values.items():
            self._status_variables[name].set(value)
        state = self._supervisor.state.state
        self._banner.configure(
            text=prominent_status(state),
            bg="#b91c1c" if state in {AppState.ARMED, AppState.RUNNING} else "#374151",
        )
        available = buttons_for(
            state,
            control_permission=(
                self._supervisor.controller is not None
                and self._supervisor.controller.permission_healthy
            ),
        )
        for key, button in self._buttons.items():
            button.configure(state="normal" if getattr(available, key) else "disabled")

    def _shutdown(self) -> None:
        self._stop.set()
        if self._source is not None:
            self._source.close()
        with self._supervisor_lock:
            self._supervisor.close()
        self._runtime_files.release_control()
        if self._worker is not None:
            self._worker.join(timeout=3.5)
        self._root.destroy()
