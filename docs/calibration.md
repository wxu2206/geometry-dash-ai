# Calibration

Calibration estimates the relationship between captured pixels, observed motion,
input latency, and collision behavior. It must learn from live observations rather
than importing Geometry Dash constants or level data.

## Alpha capture setup

The alpha supplies `geometry-dash-ai calibrate --backend portal` for the normal KDE
source-selection dialog, validated crop setup, and optional manual color-patch
sampling. Follow it with `geometry-dash-observe --preview` for local overlays.
It is observe-only and does not estimate dynamics or send test inputs. Details,
including KDE Wayland limitations, are in [capture.md](capture.md).

## Setup Calibration

The setup workflow is:

1. Launch Geometry Dash and open a playable level.
2. Open the main app's Setup dialog or run `geometry-dash-ai calibrate --backend portal`; approve KDE’s dialog and
   select the game window (preferred) or monitor.
3. If a monitor was selected, choose a relative crop with command options;
   validate it and save only after the reported dimensions are correct.
4. Optionally use `--sample-player` over a cube patch, then run
   `geometry-dash-ai shadow --preview --shadow-log calibration.jsonl`.
5. Confirm player box, ground/spike/block boxes, status confidence, scroll,
   capture latency, and the cyan shadow trajectory. Adjust local TOML and repeat.
6. Keep a short manual-play shadow log to compare visual survival/death outcome
   against recommendations. No input interception or injection occurs.

Machine-specific results live under `data/calibration/` and are ignored by Git.

While Observe or Shadow is open, play several normal cube jumps manually. The
bounded visual collector recognizes high-confidence upward arcs without reading
keyboard events, converts screen y to positive-up physics coordinates, rejects
lost/mode-uncertain samples, robustly fits a quadratic after enough samples, and
saves `data/calibration/physics.json`. Live arming remains unavailable until a
valid minimum-sample model exists. Corrupt models are ignored safely.

## Cube Parameters

Estimate horizontal scroll/player speed, jump initial velocity, gravity, jump
duration, collision-box inset, and landing response. Track multiple unobstructed
jumps and fit vertical position to a constant-acceleration model:

```text
y(t) = y0 + v0*t + 0.5*g*t^2
```

The implemented `CubePhysicsCalibrator` uses monotonic frame timestamps, least
squares, and median-absolute-deviation rejection so dropped frames and imperfect
box detections do not bias estimates. Treat takeoff and landing observations as
separate latency/collision measurements.

## Ship Parameters

Collect short, safety-bounded hold and release pulses. Fit upward acceleration,
downward acceleration, velocity limits, and input response delay from tracked
motion. Do not collect calibration samples when the player is occluded, dying, or
near uncertain geometry.

## Online Adaptation

Each predicted trajectory is paired with later observations. Residuals update
parameters using bounded exponential adaptation (default learning rate `0.05`).
Updates require enough high-confidence observations and are rejected when they
would violate physical constraints. Maintain uncertainty per parameter; planner
safety margins grow when uncertainty or residual error grows.

Prediction failures are categorized before adaptation:

- consistent vertical error suggests gravity/impulse/acceleration correction;
- timing-shifted response suggests latency correction;
- correct motion but wrong collision suggests collision-box adjustment;
- all geometry shifted together suggests coordinate/scroll alignment correction;
- isolated low-confidence errors should not update the model.

Current alpha ship calibration is not yet connected to automatic persistence;
ship MPC starts from conservative validated defaults. This is a live-tuning
limitation, not a claim of calibrated Stereo Madness ship behavior.

## Validation

Replay observations through the estimator and report held-out position error,
collision-time error, parameter confidence, and rejected samples. The synthetic
environment provides known constants for calibration-math unit tests. Never tune
parameters to progress percentage or a known Stereo Madness timestamp.
