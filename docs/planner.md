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

At minimum, generate no jump, jump now, jumps after one through three capture
frames, and several later offsets within the horizon. Simulate takeoff, gravity,
collisions, landings, and continued motion for each candidate.

Score candidates using:

- collision probability and time-to-collision;
- minimum obstacle clearance;
- landing position and usable platform margin;
- uncertainty cost; and
- unnecessary-action cost.

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

Synthetic tests cover isolated and grouped spikes, blocks, gaps, safe and unsafe
landings, low ceilings, narrow ship corridors, portal transitions, delayed input,
geometry uncertainty, and cases with no safe trajectory. Planner outputs should be
deterministic for a fixed snapshot and configuration.

