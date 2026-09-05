# Calibration

Calibration estimates the relationship between captured pixels, observed motion,
input latency, and collision behavior. It must learn from live observations rather
than importing Geometry Dash constants or level data.

## Setup Calibration

The planned setup UI will:

1. Let the user position a capture rectangle without editing source code.
2. Confirm frame delivery, timestamp stability, and measured capture FPS.
3. Preview candidate player boxes and geometry overlays.
4. Establish image-to-physics coordinate scaling and the visible ground line.
5. Verify pause, manual override, and emergency stop while input is disabled.

Machine-specific results live under `data/calibration/` and are ignored by Git.

## Cube Parameters

Estimate horizontal scroll/player speed, jump initial velocity, gravity, jump
duration, collision-box inset, and landing response. Track multiple unobstructed
jumps and fit vertical position to a constant-acceleration model:

```text
y(t) = y0 + v0*t + 0.5*g*t^2
```

Use monotonic frame timestamps and robust fitting so dropped frames and imperfect
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

## Validation

Replay observations through the estimator and report held-out position error,
collision-time error, parameter confidence, and rejected samples. The synthetic
environment provides known constants for calibration-math unit tests. Never tune
parameters to progress percentage or a known Stereo Madness timestamp.

