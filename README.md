# Geometry Dash AI

Geometry Dash AI `0.2.0a1` is a local, vision-based alpha designed to attempt
Stereo Madness from rendered pixels. It combines KDE Wayland portal capture,
classical perception, tracked local geometry, cube trajectory planning, ship
model-predictive control, visual run-state detection, guarded portal input, and
local calibration. It does not read game memory or level files and has no
timestamp/progress click script.

> This alpha has completed its synthetic pixel-boundary cube → ship → cube demo.
> It has **not** been verified completing Stereo Madness live. Capture and input
> portal flows still require the user to approve KDE dialogs on the real desktop.

## Quick start

```bash
cd /var/home/will/geometry-dash-ai
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,live]'
geometry-dash-ai doctor
geometry-dash-ai demo
geometry-dash-ai
```

`python -m geometry_dash_ai` is equivalent to the main command. Other useful
commands are:

```bash
geometry-dash-ai calibrate --backend portal --write-local
geometry-dash-ai observe --frames 300 --preview
geometry-dash-ai shadow --frames 300 --preview
geometry-dash-ai benchmark
geometry-dash-ai stop
```

## Application workflow

On first launch, Setup saves validated machine-local crop, vision, retry, live
control, and recording settings to ignored `config/local.toml`. Launch Geometry
Dash, choose Stereo Madness, then Start Observe. KDE asks which single window or
monitor may be captured. Prefer the game window; monitor capture is cropped
immediately to the configured rectangle.

Observe displays the validated local frame, tracked player, floor, solids,
spikes, ceiling, mode, rates, latency, and confidence. Shadow adds cube candidate
planning, a selected trajectory, a useful alternative, predicted landing and
collision markers, and recommendations—but cannot send input.

Live control is a separate opt-in sequence: enable it in Setup, acknowledge the
warning, enter Shadow, request KDE keyboard permission, click Arm, wait through
the visible countdown, then click Start AI. Permission, arming, and running are
distinct states. The only generated key is a bounded Space action. No pointer,
typing, clipboard, or generic automation API exists.

## What works

- Explicit application state machine and responsive loopback-only browser dashboard.
- ScreenCast portal capture on the user session bus, one user-selected source,
  ephemeral PipeWire FD, fixed local GStreamer reader, bounded crop and cleanup.
- RGB/chroma player signatures, component shape/size checks, temporal prior,
  cube/ship mode smoothing, bounded prediction/reacquisition, velocity and
  acceleration estimates.
- Conservative floor, gap, platform, ceiling, and triangular spike perception
  with bounded temporal fusion and player-relative coordinate conversion.
- Survival-first cube planner with swept collision, landing margins, timing
  variants, uncertainty, candidate rationale, and stale-decision rejection.
- Dedicated ship dynamics and deterministic bounded binary MPC with collision
  dominance, clearance, uncertainty, switching cost, and hysteresis.
- Visual manual-jump collection, robust quadratic cube fit, outlier rejection,
  bounds, last-known-good calibration, and versioned JSON persistence.
- Visual active/death/reset/completion preparation, bounded attempts and retry,
  owner-only local emergency-stop flag, exclusive live-control lock, watchdogs,
  local bounded run summaries, and frames off by default.
- Deterministic headless CI and a pixel-boundary synthetic application demo.

## Safety and privacy

The default configuration disables live control and diagnostic recording. Live
action dispatch fails closed on stale capture, missing player, unknown mode, low
geometry/tracking readiness, planner failure, portal permission loss, heartbeat
loss, excessive hold, session expiry, capture failure, shutdown, or Emergency
Stop. One process at a time may own live control. `geometry-dash-ai stop` uses an
owner-only runtime file under `XDG_RUNTIME_DIR`; it exposes no network service.

Frames stay local, are never uploaded, and are not placed in logs. Raw diagnostic
frames are off by default and, if explicitly enabled by tooling, remain in the
ignored bounded `data/frames` area. Portal capability/session values are neither
persisted nor logged. Compact run/calibration records stay under ignored `data/`.

## Architecture

```text
portal capture -> validated latest frame -> perception/tracking -> local geometry
      -> cube planner or ship MPC -> runtime readiness gate -> guarded Space backend
                    |                         |
                    +-> overlay/shadow        +-> visual outcome/calibration/history
```

The packages remain separated into `app`, `capture`, `vision`, `tracking`,
`physics`, `planning`, `control`, `learning`, `telemetry`, `ui`, `config`, and
`simulation`. See [architecture](docs/architecture.md), [capture](docs/capture.md),
[perception](docs/perception.md), [planner](docs/planner.md), and the
[user guide](docs/user-guide.md).

## Bazzite / KDE Wayland

Direct `mss` capture is commonly denied by the compositor and is not bypassed.
The supported path is the normal ScreenCast portal and PipeWire. The pure-Python
`dbus-next` dependency lives in `.venv`; GStreamer/PipeWire must already exist in
the user environment. Never use `sudo`, `dnf`, `rpm`, `rpm-ostree`, host package
installation, compositor weakening, or protected system writes for this project.
See [Bazzite setup](docs/bazzite-setup.md).

## Development

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy src
.venv/bin/python -m pytest
.venv/bin/python -m compileall -q src tests scripts
.venv/bin/python -m pip check
git diff --check
```

Runtime artifacts, local config, recordings, calibration, and models are ignored
by Git. The alpha is limited to cube/ship mechanics and needs calibration and
live visual validation for the user’s game resolution/theme. RemoteDesktop
behavior can vary by portal version. See [known limitations](docs/user-guide.md#known-limitations).

## Security and legal

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
This independent research project is not affiliated with or endorsed by RobTop
Games. Geometry Dash names and assets belong to their respective owners. Use
automation responsibly and comply with relevant game/platform rules.
