# Trajectory Planner

The planner is a receding-horizon controller. It reasons over detected local
geometry and estimated dynamics, applies only the next action, then replans from a
new visual observation. It never selects actions from elapsed level time or
progress percentage.

## Common Inputs and Outputs

Inputs are a timestamped player state, mode confidence, local collision map,
calibrated physics distribution, input latency estimate, and current held-input
state. Each output records its candidate set, score components, selected next
action, expiry time, expected outcome, and confidence.

Every simulated trajectory carries an uncertainty envelope. Collision probability
comes from overlap between that envelope and inflated obstacle geometry. Clearance
and safe-region margins use the same uncertainty, so low-confidence perception
causes conservative behavior.

## Cube Planning

Phase 2 implements cube planning as deterministic pure computation in
`physics/cube.py`, `physics/geometry.py`, `planning/candidates.py`, and
`planning/cube.py`. It has no live capture or input dependency.

### State and Units

`CubeState` records lower-left x/y position, horizontal and vertical velocity,
positive collision-box width/height, grounded/alive flags, and simulation time.
The physics coordinate system is Cartesian (positive y is up). Units are abstract
but consistent: velocity is units/second and acceleration is units/second². The
fixed time step defaults to 1/60 second and never uses a wall clock.

Every state, physics parameter, geometry coordinate, dimension, horizon, and
score weight is checked for type, finiteness, sign, and a conservative magnitude
bound. State collision dimensions must match the calibrated physics dimensions.

### Collision Geometry

- `FloorSegment` is a finite top surface. Its absence creates a gap.
- `SolidRect` is an AABB with a safe top face and fatal side/underside faces.
- `Spike` is an isosceles triangle defined by its base and apex.
- `LocalGeometry` is immutable and contains at most 1,024 items; each plan keeps
  at most 256 nearest items (128 by default).

Solid face crossings are solved continuously between fixed-step states. This
prevents a fast cube from tunneling through a thin block. Top crossings while
descending produce landings; side and underside crossings are fatal. Falling
below the local map's validated `death_y` boundary produces a gap collision.

Spike collision is not a bounding-box kill test. The triangle is Minkowski-summed
with the cube's half extents, producing a convex polygon. The swept cube-center
segment is intersected with that polygon to find the first continuous collision
time. This permits safe traversal through empty corners of the spike bounding box
while preventing high-speed tunneling.

### Candidate Generation

Candidates always include no input, jump now, and jumps after one, two, and three
physics frames. Additional delays use configurable maximum and increment values.
Generation is deterministic and capped at 64 candidates (16 by default); delays
are capped at 240 frames. Defaults evaluate 16 candidates through a 24-frame
maximum delay at two-frame increments, while always including frames 1 and 3.
A delayed jump advances through every intermediate physics step and collision
check, then jumps only if the cube is grounded at that step.

### Trajectory Results

Each `CubeTrajectory` contains ordered state samples, survival status, typed
collision metadata, all observed landings, whether the requested jump occurred,
minimum relevant clearance, and simulated duration. A collision identifies its
type, time, position, and obstacle. A landing identifies the surface and cube
center position. Landing margin is the smaller distance from the center to either
usable edge after accounting for half the cube width.

Clearance is the minimum geometric separation from non-supporting solids and
nearby floor/gap edges within a configured local relevance distance. Spike
clearance conservatively uses the triangle's bounding rectangle for speed; only
the lethal collision test uses the exact triangle. Distant obstacles are capped
out of the metric and cannot inflate scores indefinitely.

### Scoring

The inspectable `ScoreComponents` fields are:

- survival (dominant ±10,000 component);
- clearance;
- landing margin;
- stable grounded terminal state;
- timing robustness and timing risk;
- geometry uncertainty;
- unnecessary jump cost; and
- requested-but-invalid jump cost.

Selection also compares survival lexicographically before total score, so even
adversarial but valid scoring configuration cannot make a fatal path beat a safe
one. With no hazard, the jump cost makes no input preferable.

### Timing Robustness

Each jump is simulated at the nominal delay and at bounded neighboring delays
(±1 frame by default, configurable up to ±3). The safe fraction is recorded and
fragile paths receive a timing-risk penalty. Variants reuse the nominal result and
do not recursively generate more candidates, keeping work bounded.

If every candidate dies, the planner sets `all_candidates_unsafe`, selects the
best fatal path by survival time and secondary metrics, and returns the predicted
collision and time to death. An already-dead cube produces an explicit
`already_dead` collision rather than raising or becoming alive.

The public entry point is:

```python
decision = plan_cube_action(state, local_geometry, physics, planner_config)
```

It returns the selected action/delay, all evaluated trajectories and score
breakdowns, confidence, unsafe-state metadata, and a debug reason. Identical
immutable inputs produce equal outputs.

A fixed distance-to-spike trigger is explicitly out of scope. Distance is only an
input to a simulated trajectory in the reconstructed local collision map.

## Ship Model-Predictive Control

Generate short sequences such as release, hold, hold→release, release→hold,
hold→hold→release, and release→release→hold. Simulate continuously over each
segment and re-plan every fresh state.

Score collision probability first, followed by floor/ceiling/obstacle clearance,
safe corridor centerline, smoothness, switching cost, and uncertainty. Centerline
preference must not overpower a collision-free path around local obstacles.

## Death Forecast

For the current policy and alternatives, expose predicted collision location,
time until collision, responsible obstacle, probability/confidence, and the safest
available alternative. A no-safe-candidate result must be explicit, not disguised
as a confident action.

## Test Strategy

Synthetic tests cover isolated and grouped spikes, spike grazing, blocks, gaps,
safe and unsafe landings, continuous collision/tunneling regressions, delayed
input, invalid numbers and dimensions, resource limits, timing fragility, and
cases with no safe trajectory. Ship corridor and portal-planner tests remain a
Phase 5 concern. Planner outputs are deterministic for a fixed snapshot and
configuration.
