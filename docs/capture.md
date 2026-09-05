# Capture and Observe-Only Runtime

Phase 3 captures only the configured rectangle. It never requests window titles,
clipboard data, game memory, level files, or a full-desktop recording.

## Configuration

Use `config/local.toml`, which is ignored by Git:

```toml
[capture]
left = 100
top = 120
width = 1280
height = 720
target_fps = 60
backend = "mss"
preview_scale = 1.0
diagnostic_mode = false
latest_frame_capacity = 1
```

The region is limited to 7680×4320 pixels, the target rate to 240 FPS, and the
latest-frame capacity to four. The normal capacity of one intentionally drops
old frames instead of accumulating latency.

`mss` is an optional user-space extra:

```bash
python -m pip install -e '.[dev,live]'
```

Run the observer with:

```bash
geometry-dash-observe --frames 120
# or
python -m geometry_dash_ai.vision --frames 120 --preview
```

For a headless perception smoke test that uses no desktop capture:

```bash
python scripts/perception_demo.py --frames 120
```

The runtime reports capture/perception rates and confidence. It has no import
of the control package, no input backend argument, and no press/click/release
operation.

## Bazzite KDE Wayland

Wayland may deny `mss` access even when `DISPLAY` is present. The backend fails
with `CaptureUnavailable` and explains that an approved desktop portal/session
capture path is needed. It does not change compositor settings, weaken portal
permissions, or fall back to desktop-wide capture. Use the synthetic backend
for CI and development when capture is unavailable.

## Calibration

Validate manual bounds without editing source:

```bash
geometry-dash-calibrate --left 100 --top 120 --width 1280 --height 720
```

After one validated frame, `--write-local` writes only `config/local.toml`.
Refusing symlinks and paths outside that fixed destination prevents arbitrary
calibration writes. A preview is optional and uses a local Tk window only.

## Recording and Privacy

The diagnostic frame buffer is disabled by default. It has a fixed in-memory
capacity, a 512 MiB total-memory ceiling, and writes compressed event data only
when an explicit caller invokes its event-write method. Writes are confined to
the active project's `data/frames/` directory, which is ignored by Git.
Telemetry contains counters and confidence, never raw pixels. No frames are
uploaded or shared by this project.
