# Phase 3 Perception

The Phase 3 stack is classical, deterministic, and intended as a calibration
baseline rather than a universal Geometry Dash detector.

## Coordinates

Captured pixels use image coordinates: `(0, 0)` is top-left, x increases right,
and y increases down. `ScreenBox` uses those coordinates.

At the planner boundary, `CoordinateTransform` makes the tracked player's
lower-left collision-box corner `(0, 0)`. x remains rightward; y is inverted so
it increases upward. One planner unit is one captured pixel until live
calibration establishes a scale. A solid's screen bottom becomes its planner
bottom; a spike's screen bottom becomes its base. Floor segments therefore
preserve visible gaps as absence of a segment.

## Detection

`ClassicalPlayerDetector` uses calibration-color signatures for the synthetic
cube (magenta) and ship (cyan). `geometry-dash-calibrate --sample-player` can
derive a median RGB cube signature from a user-selected patch, avoiding source
edits and suppressing one-pixel effects. It finds bounded connected components and emits
`PlayerDetection` with a confidence. It returns no player rather than forcing a
low-confidence classification.

`ClassicalGeometryDetector` intentionally detects only useful, high-contrast
objects: bright horizontal floor/ceiling runs, bright rectangular solids, and
red triangular-hazard candidates. Decorations, portals, effects, custom player
colors, and unusual themes are not yet reliable. The detector's output remains
screen-space and carries its own confidence.

## Tracking and Fusion

`PlayerTracker` uses monotonic timestamps, smooths finite velocity estimates,
caps velocity, rejects non-increasing timestamps, decays confidence during
misses, and smooths cube/ship mode votes. `ScrollEstimator` tracks geometry
anchors rather than player movement. `GeometryFuser` retains a bounded history
and blends overlapping boxes to reduce one-frame jitter; it never reconstructs
an unbounded map.

`PerceptionSnapshot.perception_unreliable` is true for missing/aged player
tracking or low player/geometry confidence. Downstream planners must treat it
as a display-only warning in this phase.

## Planner Preview

`preview_cube_plan(snapshot)` may compute a Phase 2 recommendation for a
high-confidence grounded cube, such as `JUMP +2 FRAMES`. It is deliberately a
pure return value. The observe-only runtime does not import, construct, or call
an input controller.

## Shadow Mode

The runtime evaluates that preview for every reliable cube snapshot and labels
the window `OBSERVE ONLY`. It displays `JUMP +N frames` or `NO INPUT`, selected
score/confidence, all-candidates-unsafe state, predicted collision, and the safe
timing-variant fraction. A cyan selected trajectory is drawn in player-relative
coordinates and a red marker denotes a predicted collision.

These are pixels and telemetry only: no action object crosses into a control
backend, and the observe runtime does not import `geometry_dash_ai.control`.
The planner only recommends while player tracking, visible floor, geometry, and
confidence are sufficient; ship predictions remain unavailable rather than guessed.

## Debug View

`render_debug_overlay` draws player, floor, solid, spike, and ceiling boxes in
different colors. `TkDebugViewer` can show that local overlay with mode,
velocity, scroll, FPS, and confidence status. It has no global keyboard/mouse
hooks and closes with the observation runtime.
