# Architecture

## Design Goals

Geometry Dash AI must make decisions from live rendered pixels and simulated
input, with no level-file parsing, memory inspection, extracted internal state,
or timestamp macros. Components are deliberately separated so observations,
uncertainty, predictions, actions, and outcomes remain inspectable.

## Runtime Data Flow

```mermaid
flowchart TD
    Capture[Capture service] --> Frame[Timestamped frame]
    Frame --> Vision[Player + geometry perception]
    Vision --> Tracking[Temporal tracker]
    Tracking --> World[Local world model]
    World --> Estimator[Physics estimator]
    Estimator --> Simulator[Trajectory simulator]
    World --> Simulator
    Simulator --> Forecast[Collision forecasts]
    Forecast --> Planner[Mode-specific planner]
    Planner --> Safety[Safety supervisor]
    Safety --> Controller[Input controller]
    Controller --> Game[Geometry Dash]
    Game --> Capture
    Tracking --> Outcomes[Death / completion detector]
    Outcomes --> Learning[Parameter adaptation]
    Learning --> Estimator
    Outcomes --> Telemetry[Telemetry + event recorder]
    Forecast --> Telemetry
```

## Module Boundaries

- `capture`: owns frame acquisition, timestamps, measured FPS, capture-region
  selection, and a latest-frame interface. It does not interpret pixels.
- `vision`: turns a frame into uncertain player and geometry detections using
  classical computer vision first. It has no authority to send input.
- `tracking`: associates observations over time and estimates position, velocity,
  mode, confidence, and stable local geometry.
- `physics`: owns validated geometry and parameters and simulates trajectories.
  Phase 2 supplies deterministic fixed-step cube dynamics, continuous solid-face
  collisions, triangular spike collision, gaps, and structured landing/collision
  results. Calibration and uncertainty distributions arrive in later phases.
- `planning`: generates bounded mode-specific candidates and scores survival,
  clearance, landing quality, timing robustness, and uncertainty. Phase 2 supplies
  the cube planner; ship MPC remains isolated for Phase 5.
- `control`: converts abstract press/hold/release decisions to one replaceable
  input backend. A safety supervisor owns pause, override, and emergency release.
- `learning`: compares predicted and observed outcomes, then makes bounded,
  explainable calibration updates.
- `telemetry`: records versioned events and aggregate run statistics without
  participating in action selection.
- `ui`: renders calibration and debug overlays from snapshots of other modules.
- `simulation`: supplies deterministic synthetic observations and known physics
  for development and CI; it is not a representation of Stereo Madness data.
- `config`: loads validated TOML and provides immutable settings.

## Shared Runtime Models

Future live components should communicate through immutable snapshots:

1. `CapturedFrame`: monotonic timestamp, frame number, pixel buffer, region.
2. `PlayerObservation`: bounding box, mode probabilities, confidence.
3. `GeometryObservation`: typed shapes and confidences in screen coordinates.
4. `TrackedWorld`: player kinematics plus player-relative collision geometry.
5. `TrajectoryCandidate`: action sequence, state samples, uncertainty envelope.
6. `CollisionForecast`: time, location, obstacle, probability, alternative.
7. `ActionDecision`: action, duration, rationale, confidence, decision timestamp.

Pixel buffers should be passed by reference/read-only view where practical. State
consumers must tolerate dropped frames and use monotonic time, not assume 60 FPS.

## Coordinates

Capture and vision naturally use image coordinates (origin at top-left, positive y
down). Physics uses Cartesian local coordinates (positive y up). A tested transform
at the tracking boundary converts between them. World geometry is maintained in
player-relative coordinates for planning, while screen/world mappings carry an
estimated scroll offset and uncertainty.

## Concurrency

Capture should own a bounded latest-frame slot instead of an unbounded queue.
Perception consumes the newest available frame, and control works from an atomic
world snapshot. Recording receives sampled/event frames through a bounded queue;
storage delays must never block emergency stop or input release.

## Safety Invariants

- Input starts disabled.
- Emergency stop immediately releases every held control before other cleanup.
- Stale frames or low-confidence state result in a safe release/pause policy.
- Planner actions expire; a controller never holds indefinitely without renewal.
- Telemetry, progress estimates, and attempt counts never directly trigger input.
- Untrusted calibration/model data is validated before use.
- Planner inputs reject NaN/infinity, malformed geometry, invalid dimensions, and
  excessive magnitudes before simulation.
- A plan processes at most 256 local geometry items, 64 nominal candidates, seven
  timing variants per candidate, 1,200 fixed steps per trajectory, and a five
  second horizon. Defaults are substantially smaller.
- Candidate simulation does not mutate caller-owned state or geometry.

## Phase 2 Planning Boundary

The cube planner accepts a `CubeState`, `LocalGeometry`, calibrated
`CubePhysicsParameters`, and `CubePlannerConfig`. Its `PlanDecision` is directly
consumable by future control/debug layers and includes every candidate trajectory,
individual score components, confidence, and explicit unavoidable-death metadata.
The synthetic planner has no imports from capture, desktop input, telemetry, or
wall-clock services.

## Delivery Phases

The implementation follows the seven phases in the README. Each phase keeps CI
headless and deterministic, while live-game checks remain explicit manual tests.
