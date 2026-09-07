"""Loopback-only browser UI for the local usable-alpha application.

The active Bazzite Python may be built without Tk. This presentation layer uses
only the standard library, binds an ephemeral listener to ``127.0.0.1``, and
contains no external assets, remote API, or browser-launch side effect.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
import secrets
import threading
from collections import deque
from dataclasses import asdict, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import monotonic, monotonic_ns
from typing import Any, ClassVar, cast
from urllib.parse import urlsplit

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

LOOPBACK_HOST = "127.0.0.1"
MAX_REQUEST_BYTES = 4_096
MAX_PREVIEW_BYTES = 4 * 1024 * 1024


class AlphaUiUnavailable(RuntimeError):
    """Presentation startup failed; retained as a public error category."""


class _LoopbackServer(ThreadingHTTPServer):
    """Fixed loopback listener. Request workers are joined at shutdown."""

    daemon_threads = False
    allow_reuse_address = False


class AlphaLocalWebApplication:
    """Run the alpha supervisor with a local browser dashboard."""

    def __init__(
        self,
        config: AppConfig,
        project_root: Path,
        runtime_files: LocalRuntimeFiles | None = None,
    ) -> None:
        self._config = config
        self._project_root = project_root.resolve()
        calibration_store = CalibrationStore(self._project_root)
        self._calibration = VisualCubeCalibrationCollector(
            calibration_store,
            minimum_samples=config.calibration.minimum_observations,
            learning_rate=config.calibration.learning_rate,
        )
        self._calibration_enabled = config.calibration.enabled
        self._supervisor = RuntimeSupervisor(
            setup_complete=(self._project_root / "config" / "local.toml").exists(),
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
        try:
            self._runtime_files = runtime_files or LocalRuntimeFiles()
        except OSError as exc:
            raise AlphaUiUnavailable(
                "could not create user-local emergency-stop files under XDG_RUNTIME_DIR"
            ) from exc
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._source: FrameSource | None = None
        self._latest: deque[tuple[PerceptionSnapshot, np.ndarray[Any, Any]]] = deque(maxlen=1)
        self._latest_lock = threading.Lock()
        self._last_snapshot: PerceptionSnapshot | None = None
        self._last_error: str | None = None
        self._token = secrets.token_urlsafe(32)
        self._server: _LoopbackServer | None = None
        self._serving = False

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("local UI server has not been started")
        host, port = self._server.server_address[:2]
        if host != LOOPBACK_HOST:
            raise RuntimeError("refusing a non-loopback UI address")
        return f"http://{host}:{port}/"

    def start_server(self) -> str:
        """Start a random-port loopback server; this never opens a browser."""
        if self._server is None:
            try:
                self._server = _LoopbackServer((LOOPBACK_HOST, 0), self._handler_type())
            except OSError as exc:
                raise AlphaUiUnavailable(
                    "could not bind the local 127.0.0.1 UI server; "
                    "check local socket permissions"
                ) from exc
        return self.url

    def run(self) -> None:
        print(f"Geometry Dash AI local interface: {self.start_server()}")
        print("Open this address in a local browser. Press Ctrl+C to stop safely.")
        assert self._server is not None
        try:
            self._serving = True
            self._server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            print("Stopping Geometry Dash AI.")
        finally:
            self._serving = False
            self.close()

    def close(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            if self._serving:
                server.shutdown()
            server.server_close()
        self._stop.set()
        if self._source is not None:
            self._source.close()
        with self._supervisor_lock:
            self._supervisor.close()
        self._runtime_files.release_control()
        if self._worker is not None:
            self._worker.join(timeout=3.5)

    def status_payload(self) -> dict[str, object]:
        """JSON-safe status; it intentionally contains no pixels or portal tokens."""
        with self._supervisor_lock:
            dashboard = self._supervisor.dashboard(self._last_snapshot)
            controller = self._supervisor.controller
            buttons = buttons_for(
                self._supervisor.state.state,
                control_permission=controller is not None and controller.permission_healthy,
            )
        source = self._source
        result = asdict(dashboard)
        result.update(
            {
                "banner": prominent_status(AppState(dashboard.status.lower())),
                "capture_fps": 0.0 if source is None else round(source.capture_fps, 2),
                "dropped_frames": 0 if source is None else source.dropped_frames,
                "buttons": asdict(buttons),
                "preview_available": self._preview_image() is not None,
                "last_ui_error": self._last_error,
            }
        )
        return result

    def diagnostics_payload(self) -> dict[str, object]:
        return {
            "checks": [asdict(check) for check in run_doctor(self._project_root)],
            "capture_worker": "alive"
            if self._worker is not None and self._worker.is_alive()
            else "stopped",
        }

    def dispatch(self, action: str, payload: dict[str, object]) -> dict[str, object]:
        """Dispatch a fixed allowlist of UI actions, never arbitrary methods."""
        try:
            button_name = {
                "setup": "setup",
                "reset": "reset",
                "observe": "observe",
                "shadow": "shadow",
                "request_control": "request_control",
                "arm": "arm",
                "start": "start",
                "pause": "pause",
                "resume": "resume",
                "emergency_stop": "emergency_stop",
            }.get(action)
            if button_name is None:
                raise ValueError("unknown local UI action")
            with self._supervisor_lock:
                controller = self._supervisor.controller
                available = buttons_for(
                    self._supervisor.state.state,
                    control_permission=controller is not None and controller.permission_healthy,
                )
            if not getattr(available, button_name):
                raise RuntimeError(f"{action} is unavailable in the current application state")
            if action == "setup":
                self._save_setup(payload)
            elif action == "reset":
                self._reset_local()
            elif action == "observe":
                self._start_observe()
            elif action == "shadow":
                with self._supervisor_lock:
                    self._supervisor.enter_shadow()
            elif action == "request_control":
                self._request_control(payload)
            elif action == "arm":
                self._arm()
            elif action == "start":
                with self._supervisor_lock:
                    self._supervisor.start(monotonic_ns())
            elif action == "pause":
                with self._supervisor_lock:
                    self._supervisor.pause()
            elif action == "resume":
                with self._supervisor_lock:
                    self._supervisor.resume(monotonic_ns())
            elif action == "emergency_stop":
                self._emergency_stop()
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._last_error = str(exc)
            return {"ok": False, "error": str(exc), "status": self.status_payload()}
        return {"ok": True, "status": self.status_payload()}

    def preview_bmp(self) -> bytes | None:
        """Return only the latest local overlay as a bounded BMP response."""
        image = self._preview_image()
        if image is None:
            return None
        height, width, channels = image.shape
        if channels != 3 or height <= 0 or width <= 0:
            return None
        row_bytes = width * 3
        padded = (row_bytes + 3) & ~3
        payload_size = padded * height
        total_size = 54 + payload_size
        if total_size > MAX_PREVIEW_BYTES:
            return None
        header = bytearray(54)
        header[0:2] = b"BM"
        header[2:6] = total_size.to_bytes(4, "little")
        header[10:14] = (54).to_bytes(4, "little")
        header[14:18] = (40).to_bytes(4, "little")
        header[18:22] = width.to_bytes(4, "little", signed=True)
        header[22:26] = height.to_bytes(4, "little", signed=True)
        header[26:28] = (1).to_bytes(2, "little")
        header[28:30] = (24).to_bytes(2, "little")
        header[34:38] = payload_size.to_bytes(4, "little")
        bgr = np.ascontiguousarray(image[:, :, ::-1])
        if padded == row_bytes:
            return bytes(header) + cast(bytes, bgr.tobytes())
        pixels = bytearray(payload_size)
        for index in range(height):
            start = index * padded
            pixels[start : start + row_bytes] = cast(bytes, bgr[index].tobytes())
        return bytes(header) + bytes(pixels)

    def _preview_image(self) -> np.ndarray[Any, Any] | None:
        with self._latest_lock:
            if not self._latest:
                return None
            image = self._latest[-1][1]
        scale = min(1.0, 900.0 / image.shape[1], 600.0 / image.shape[0])
        try:
            return np.ascontiguousarray(scale_preview(image, scale))
        except ValueError:
            return None

    def _save_setup(self, payload: dict[str, object]) -> None:
        values = {
            key: _payload_int(payload, key)
            for key in (
                "crop_left",
                "crop_top",
                "crop_width",
                "crop_height",
                "target_fps",
                "color_tolerance",
                "maximum_attempts",
            )
        }
        candidate = replace(
            self._config,
            capture=replace(
                self._config.capture,
                left=values["crop_left"], top=values["crop_top"],
                width=values["crop_width"], height=values["crop_height"],
                target_fps=values["target_fps"],
            ),
            vision=replace(self._config.vision, color_tolerance=values["color_tolerance"]),
            control=replace(
                self._config.control,
                enabled=_payload_bool(payload, "live_control"),
                auto_retry=_payload_bool(payload, "auto_retry"),
                maximum_attempts=values["maximum_attempts"],
            ),
            recording=replace(self._config.recording, enabled=_payload_bool(payload, "recording")),
            calibration=replace(self._config.calibration, enabled=_payload_bool(payload, "calibration")),
        )
        save_local_config(self._project_root, candidate)
        self._config = candidate
        self._calibration_enabled = candidate.calibration.enabled
        with self._supervisor_lock:
            if self._supervisor.state.state is AppState.SETUP_REQUIRED:
                self._supervisor.setup_completed()

    def _reset_local(self) -> None:
        for target in (
            self._project_root / "config" / "local.toml",
            self._project_root / "data" / "calibration" / "physics.json",
            self._project_root / "data" / "runs" / "history.jsonl",
        ):
            parent = target.parent.resolve()
            if (
                self._project_root not in parent.parents
                or target.is_symlink()
                or target.parent.is_symlink()
            ):
                raise ValueError("refusing an unsafe reset target")
            target.unlink(missing_ok=True)

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
                if self._runtime_files.consume_stop():
                    self._emergency_stop()
                    return
                started = monotonic()
                frame = source.capture_once()
                snapshot = pipeline.process(frame)
                fitted = self._calibration.update(snapshot) if self._calibration_enabled else None
                if first:
                    with self._supervisor_lock:
                        self._supervisor.capture_ready()
                    first = False
                with self._supervisor_lock:
                    self._last_snapshot = snapshot
                    if fitted is not None:
                        self._supervisor.set_cube_calibration(fitted)
                    self._supervisor.process(
                        snapshot, completion_visual_cue=detect_completion_visual_cue(frame)
                    )
                    if self._config.control.auto_retry:
                        self._supervisor.maybe_retry(monotonic_ns())
                    if self._supervisor.state.state in {
                        AppState.SHADOW, AppState.ARMED, AppState.PAUSED,
                    }:
                        self._supervisor.plan_shadow(snapshot)
                    shadow = self._supervisor.cube_shadow
                    ship_shadow = self._supervisor.ship_shadow
                overlay = render_debug_overlay(
                    frame.image, snapshot.tracked_player.bounds, snapshot.fused_geometry, shadow, ship_shadow
                )
                with self._latest_lock:
                    self._latest.append((snapshot, overlay))
                self._stop.wait(max(0.0, interval - (monotonic() - started)))
        except Exception as exc:
            with self._supervisor_lock:
                self._supervisor.degrade(f"capture/runtime stopped: {exc}")
            self._last_error = str(exc)
        finally:
            if source is not None:
                source.close()
            self._source = None

    def _make_source(self) -> FrameSource:
        capture = self._config.capture
        region = CaptureRegion(capture.left, capture.top, capture.width, capture.height, capture.monitor)
        if capture.backend == "portal":
            return PipeWirePortalFrameSource(region, capture.target_fps)
        if capture.backend == "mss":
            return MssFrameSource(region, capture.target_fps)
        return SyntheticFrameSource(region, (np.zeros((region.height, region.width, 3), dtype=np.uint8),))

    def _request_control(self, payload: dict[str, object]) -> None:
        if not self._config.control.enabled:
            raise RuntimeError("enable the live-control workflow in Setup first")
        if not _payload_bool(payload, "acknowledge_live_control"):
            raise RuntimeError("acknowledge bounded Space-key control before requesting permission")
        self._runtime_files.acquire_control()
        try:
            backend = KdeRemoteDesktopActionBackend()
            control = self._config.control
            with self._supervisor_lock:
                self._supervisor.attach_control(
                    backend,
                    ControlLimits(
                        control.tap_duration_ms, control.maximum_hold_ms,
                        control.maximum_actions_per_second, control.heartbeat_timeout_ms,
                        control.maximum_session_seconds, control.arming_timeout_seconds,
                    ),
                )
        except Exception:
            self._runtime_files.release_control()
            raise

    def _arm(self) -> None:
        now = monotonic_ns()
        with self._supervisor_lock:
            snapshot = self._last_snapshot
            if snapshot is None:
                raise RuntimeError("no validated perception snapshot is available")
            self._supervisor.arm(now, self._supervisor.readiness(snapshot, now))

    def _emergency_stop(self) -> None:
        self._stop.set()
        with self._supervisor_lock:
            self._supervisor.emergency_stop()
        self._runtime_files.release_control()

    def _handler_type(self) -> type[BaseHTTPRequestHandler]:
        application = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "GeometryDashAI/0.2"
            sys_version = ""
            _application: ClassVar[AlphaLocalWebApplication] = application

            def log_message(self, format: str, *args: object) -> None:
                del format, args

            def do_GET(self) -> None:  # noqa: N802
                path = urlsplit(self.path).path
                if path == "/":
                    self._send(
                        HTTPStatus.OK,
                        "text/html; charset=utf-8",
                        _page(application._token, application._config),
                    )
                    return
                if not self._authorized() or path not in {"/api/status", "/api/preview", "/api/diagnostics"}:
                    self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found")
                elif path == "/api/status":
                    self._json(HTTPStatus.OK, application.status_payload())
                elif path == "/api/diagnostics":
                    self._json(HTTPStatus.OK, application.diagnostics_payload())
                else:
                    preview = application.preview_bmp()
                    self._send(
                        HTTPStatus.NO_CONTENT if preview is None else HTTPStatus.OK,
                        "image/bmp" if preview is not None else "text/plain; charset=utf-8",
                        b"" if preview is None else preview,
                    )

            def do_POST(self) -> None:  # noqa: N802
                if urlsplit(self.path).path != "/api/action" or not self._authorized():
                    self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found")
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 1 <= length <= MAX_REQUEST_BYTES:
                        raise ValueError("request size is invalid")
                    decoded = json.loads(self.rfile.read(length))
                    if not isinstance(decoded, dict):
                        raise ValueError("request payload must be an object")
                    action = decoded.get("action")
                    payload = decoded.get("payload", {})
                    if not isinstance(action, str) or not isinstance(payload, dict):
                        raise ValueError("request action is invalid")
                    self._json(HTTPStatus.OK, application.dispatch(action, payload))
                except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

            def _authorized(self) -> bool:
                return secrets.compare_digest(self.headers.get("X-GDAI-Token", ""), application._token)

            def _json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
                self._send(status, "application/json; charset=utf-8", json.dumps(payload, separators=(",", ":")).encode())

            def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(body)

        return Handler


def _payload_int(payload: dict[str, object], name: str) -> int:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _payload_bool(payload: dict[str, object], name: str) -> bool:
    value = payload.get(name)
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _page(token: str, config: AppConfig) -> bytes:
    """Self-contained local UI; the process-local token is neither logged nor saved."""
    script_token = json.dumps(token)
    setup = json.dumps(
        {
            "crop_left": config.capture.left,
            "crop_top": config.capture.top,
            "crop_width": config.capture.width,
            "crop_height": config.capture.height,
            "target_fps": config.capture.target_fps,
            "color_tolerance": config.vision.color_tolerance,
            "maximum_attempts": config.control.maximum_attempts,
            "live_control": config.control.enabled,
            "auto_retry": config.control.auto_retry,
            "recording": config.recording.enabled,
            "calibration": config.calibration.enabled,
        },
        separators=(",", ":"),
    )
    return f"""<!doctype html><meta charset=utf-8><title>Geometry Dash AI</title>
<style>body{{font:14px system-ui;background:#111827;color:#e5e7eb;margin:20px}}#banner{{padding:12px;background:#374151;font-weight:bold}}.live{{background:#b91c1c!important}}main{{display:grid;grid-template-columns:1fr 2fr;gap:16px}}section{{background:#1f2937;padding:14px}}dl{{display:grid;grid-template-columns:170px 1fr;gap:5px}}dt{{color:#9ca3af}}button{{margin:3px;padding:8px}}.danger{{background:#b91c1c;color:#fff;font-weight:bold}}img{{max-width:100%;background:#000}}fieldset{{display:grid;grid-template-columns:1fr 1fr;gap:5px}}label{{display:grid;gap:2px}}pre{{white-space:pre-wrap}} </style>
<h1>GEOMETRY DASH AI</h1><div id=banner>STARTING</div><p id=message></p><main><section><h2>Dashboard</h2><dl id=status></dl><h2>Controls</h2><div id=controls></div><label><input id=ack type=checkbox> I understand bounded Space-key control</label><h2>Setup</h2><fieldset id=setup></fieldset><button onclick=saveSetup()>Save validated setup</button><button onclick=diagnostics()>Diagnostics</button><pre id=diag></pre></section><section><h2>Validated local preview</h2><img id=preview alt="No captured preview yet"></section></main>
<script>const token={script_token},saved={setup},labels={{status:'App status',capture_status:'Capture',control_status:'Control permission',game_mode:'Game mode',attempt:'Attempt',capture_fps:'Capture FPS',perception_fps:'Perception FPS',planner_hz:'Planner Hz',latency_ms:'Latency ms',player_confidence:'Player confidence',geometry_confidence:'Geometry confidence',planner_confidence:'Planner confidence',physics_ready:'Physics calibration',dropped_frames:'Dropped frames',predicted_action:'Recommendation',risk:'Predicted risk',last_error:'Last error'}},controls=[['observe','Start Observe'],['shadow','Start Shadow'],['request_control','Request Live Control'],['arm','Arm AI'],['start','Start AI'],['pause','Pause'],['resume','Resume'],['reset','Reset Local Data'],['emergency_stop','EMERGENCY STOP']],fields=[['crop_left','Crop left'],['crop_top','Crop top'],['crop_width','Crop width'],['crop_height','Crop height'],['target_fps','Target FPS'],['color_tolerance','Player tolerance'],['maximum_attempts','Maximum attempts']];for(const[x,n]of fields)setup.insertAdjacentHTML('beforeend',`<label>${{n}}<input id=${{x}} type=number value=${{saved[x]}}></label>`);setup.insertAdjacentHTML('beforeend',`<label><input id=auto_retry type=checkbox ${{saved.auto_retry?'checked':''}}> Auto retry</label><label><input id=recording type=checkbox ${{saved.recording?'checked':''}}> Diagnostic recording</label><label><input id=calibration type=checkbox ${{saved.calibration?'checked':''}}> Learn calibration</label>`);ack.checked=saved.live_control;const headers={{'X-GDAI-Token':token}};async function get(p){{return fetch(p,{{headers}})}}async function send(action,payload={{}}){{let r=await fetch('/api/action',{{method:'POST',headers:{{...headers,'Content-Type':'application/json'}},body:JSON.stringify({{action,payload}})}}),d=await r.json();message.textContent=d.ok?'':d.error;render(d.status)}}function render(d){{if(!d)return;banner.textContent=d.banner;banner.className=d.status==='running'||d.status==='armed'?'live':'';status.innerHTML=Object.entries(labels).map(([k,n])=>`<dt>${{n}}</dt><dd>${{d[k]??'—'}}</dd>`).join('');controlsEl.innerHTML=controls.map(([k,n])=>`<button class=${{k==='emergency_stop'?'danger':''}} ${{d.buttons[k]?'':'disabled'}} onclick="act('${{k}}')">${{n}}</button>`).join('')}}const controlsEl=document.querySelector('#controls');function act(k){{if(k==='reset'&&!confirm('Delete local settings, calibration, and run history?'))return;if(k==='arm'){{banner.textContent='ARMING IN 3 — SHADOW ONLY';setTimeout(()=>send('arm'),3000);return}}send(k,k==='request_control'?{{acknowledge_live_control:ack.checked}}:{{}})}}function saveSetup(){{let p={{live_control:ack.checked,auto_retry:auto_retry.checked,recording:recording.checked,calibration:calibration.checked}};for(const[x]of fields)p[x]=Number(document.querySelector('#'+x).value);send('setup',p)}}async function diagnostics(){{diag.textContent=JSON.stringify(await(await get('/api/diagnostics')).json(),null,2)}}let objectUrl='';async function refresh(){{try{{render(await(await get('/api/status')).json());let r=await get('/api/preview');if(r.status===200){{if(objectUrl)URL.revokeObjectURL(objectUrl);objectUrl=URL.createObjectURL(await r.blob());preview.src=objectUrl}}}}catch(e){{message.textContent='Local UI error: '+e}}setTimeout(refresh,250)}}refresh();</script>""".encode()


# Compatibility alias: callers of the prior main-app class now receive the web UI.
AlphaTkApplication = AlphaLocalWebApplication
