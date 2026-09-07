# Usable alpha user guide

## Install and verify

From the repository, use only the local virtual environment:

```bash
cd /var/home/will/geometry-dash-ai
source .venv/bin/activate
python -m pip install -e '.[dev,live]'
geometry-dash-ai doctor
geometry-dash-ai demo
geometry-dash-ai
```

Doctor is read-only. Demo uses generated pixels and mock permission/input; it
does not open or control Geometry Dash.

## First launch

The app opens in Setup Required when `config/local.toml` is absent. Click Setup,
enter the crop relative to the surface you intend to select, choose whether the
live-control workflow is allowed, and save. Settings are schema-validated and
stored locally with owner-only permissions. The next launch reuses the crop,
vision tolerance, attempt policy, and diagnostic choice. RemoteDesktop permission
is deliberately never reused.

For player-color sampling, position the player visibly and use:

```bash
geometry-dash-ai calibrate --backend portal \
  --sample-player LEFT TOP WIDTH HEIGHT --write-local
```

Coordinates are relative to the selected source. The command captures one frame,
prints the sampled RGB value, saves no pixels, and exits. If a monitor was chosen,
also pass `--left`, `--top`, `--width`, and `--height`. Reopen the app afterward.

## Capture and Observe

Launch Geometry Dash manually, open Stereo Madness, and click Start Observe. KDE
shows its standard source chooser. Select the Geometry Dash window when available,
or one monitor. The dashboard should show a moving capture/perception rate and a
magenta player box. Floors are green, solids yellow, spikes red, and ceilings
blue. If confidence is poor, adjust crop, player sample, and color tolerance.

Play several normal cube jumps manually. The visual collector needs at least 30
high-confidence arc samples before it writes a validated physics model. No global
keyboard hook is used. Live AI remains gated until that calibration is valid.

## Shadow mode

Click Start Shadow after Observe stabilizes. The banner explicitly says no input.
For cube frames, cyan is the selected trajectory, gray is a useful alternative,
green marks a predicted landing, and red marks a predicted collision. The
dashboard shows action, risk, planner confidence, rate, geometry confidence, and
latency. Standalone shadow mode also writes compact decision telemetry. Its
on-disk file is capped at 5 MiB, then recording stops while observation continues:

```bash
geometry-dash-ai shadow --frames 600 --preview --shadow-log manual-check.jsonl
```

The log stays at `data/runs/manual-check.jsonl` and contains no images.

## Live mode

Live mode is experimental and must be tested with attention available:

1. Enable live control in Setup and check the on-screen acknowledgment.
2. Establish healthy Observe and Shadow operation.
3. Click Request Live Control and approve keyboard access in KDE.
4. Confirm the dashboard says permission granted but not armed.
5. Click Arm AI and watch the 3–2–1 warning countdown.
6. Click Start AI while Geometry Dash is the intended target.

The backend requests keyboard only and can emit only Space. Cube mode issues
bounded taps for current-frame jump decisions. Ship mode executes only the first
held/released portion of a bounded short-horizon plan, then observes and replans.
Mode changes release the current action before changing controllers.

Capture freshness, player/mode/geometry/tracking/physics/planner readiness and
permission health are checked before action dispatch. Borderline or unknown state
means release and stop, even when that causes an in-game death.

## Death, retry, completion, and history

Death requires several missing-player frames plus stopped scene motion. A single
miss is not death. Auto retry uses this visual state, a cooldown, and the same
bounded Space tap; it never uses an elapsed-level timer. The default session limit
is 25 attempts and 30 minutes. Visual completion disarms and prevents another
run. Compact summaries are capped at 5 MiB in `data/runs/history.jsonl`.

The visual signals are conservative preparation and have not yet been validated
across a live full Stereo Madness run. Watch the state banner and intervene when
the run-state classification is wrong.

## Emergency Stop and shutdown

Click the large red Emergency Stop button or run this from another terminal:

```bash
cd /var/home/will/geometry-dash-ai
source .venv/bin/activate
geometry-dash-ai stop
```

The local command writes an owner-only runtime flag. The app releases Space,
disarms, closes the RemoteDesktop and ScreenCast sessions, stops capture, and
joins its worker. Window close follows the same cleanup. Only one app can own
live control; Observe-only instances do not acquire that lock.

## Data and reset

`config/local.toml`, `data/calibration`, `data/runs`, and `data/frames` are ignored
by Git. Frames are not uploaded. Diagnostic frame saving is off by default; if
explicitly enabled, event snapshots may contain unrelated screen content when a
monitor source was selected.

The Setup/Ready dashboard provides Reset Local Data with confirmation. It removes
only `config/local.toml`, `data/calibration/physics.json`, and
`data/runs/history.jsonl`; explicit diagnostic event frames are deliberately left
untouched. Restart afterward. The next launch falls back to setup/defaults.

## Troubleshooting

- Capture denied/cancelled: remain in setup/Observe and try again; no input was
  enabled.
- Direct `mss` denied: expected on KDE Wayland; use `portal`.
- GStreamer unavailable: this environment lacks the existing user-space reader;
  do not modify Bazzite. Observe with synthetic demo and report the blocker.
- Player absent: verify crop, sample the player, increase tolerance modestly, and
  check the preview for decorative false matches.
- Physics readiness false: manually play several clean cube jumps in Observe.
- Portal stream ended or desktop locked: live action releases and app degrades.
- Attempt/session limit reached: the app pauses/disarms; deliberately arm again.

## Known limitations

- Live KDE portal capture/control and actual Geometry Dash were not exercised in
  the automated coding environment because permission dialogs require the user.
- Real Stereo Madness perception thresholds, scroll accuracy, and cube parameters
  still need user-mediated live calibration and validation.
- Ship parameter learning is not yet persisted; ship MPC uses conservative
  defaults and is synthetic-tested only.
- Completion/death cues are conservative classical signals and may need tuning.
- Portal capture and RemoteDesktop currently use separate ephemeral sessions.
- The Setup dialog covers common settings; fine-grained player sampling remains
  in the `calibrate` command.
- The cube planner clears the 30 Hz synthetic benchmark target on this machine;
  portal capture and real-game perception still need user-mediated measurement.
- The alpha is designed to attempt Stereo Madness; it is not claimed to beat it.
