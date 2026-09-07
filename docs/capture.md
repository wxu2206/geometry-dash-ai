# Capture and application runtime

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
backend = "portal"
preview_scale = 1.0
diagnostic_mode = false
latest_frame_capacity = 1
```

The region is limited to 7680×4320 pixels, the target rate to 240 FPS, and the
latest-frame capacity to four. The normal capacity of one intentionally drops
old frames instead of accumulating latency.

`portal` is the recommended KDE Wayland backend. It uses the standard
`org.freedesktop.portal.ScreenCast` interface on the **user session bus**. On
each run KDE displays its usual selection dialog; choose the Geometry Dash
window where offered, or choose one monitor. The app cannot enumerate windows,
preselect a source, remember a grant, or weaken compositor policy.

The implementation sends fixed low-level D-Bus messages rather than asking
`dbus-next` to parse the portal's whole introspection XML. This avoids KDE portal
properties that are valid for the portal but rejected by some `dbus-next`
versions. It waits only for the matching `Request.Response` signal, validates
the response and returned FD handle, and removes its signal handler/match rule
after every request.

After approval, the portal returns one ephemeral PipeWire node and FD. Its
optional `size` field is compositor-coordinate metadata, not a raw-video buffer
contract. The source therefore makes a short, bounded local GStreamer caps probe
on that approved node, validates the negotiated video dimensions, then passes the
same FD only to local `gst-launch-1.0 pipewiresrc`. A leaky one-frame queue,
RGB conversion, and `videocrop` are created only after the configured `[capture]`
crop fits the negotiated source. The crop occurs before pixels enter the Python
pipe.

`dbus-next` is a normal pure-Python application dependency. The optional `live`
extra adds `mss` for the legacy direct-capture fallback; the existing user session
must already provide GStreamer’s PipeWire plugin:

```bash
python -m pip install -e '.[dev,live]'
```

Run the application or standalone observer with:

```bash
geometry-dash-ai
geometry-dash-ai observe --frames 120
# or
python -m geometry_dash_ai.vision --frames 120 --preview
```

For a headless perception smoke test that uses no desktop capture:

```bash
python scripts/perception_demo.py --frames 120
```

The runtime reports capture/perception rates, mean/recent maximum capture
latency, and confidence. It has no import
of the control package, no input backend argument, and no press/click/release
operation.

## Bazzite KDE Wayland

Wayland may deny `mss` access even when `DISPLAY` is present. Use `backend =
"portal"` instead. The portal backend fails cleanly when selection is cancelled,
denied, timed out, malformed, or lost; it closes the PipeWire process, FD, DBus
connection, and portal session on every path, including Ctrl+C. It does not
change compositor settings, weaken permissions, or fall back to hidden capture.

The portal selection is deliberately one source only. If a monitor is selected,
set `left`, `top`, `width`, and `height` relative to that selected surface; the
reader rejects a crop outside it. Prefer selecting the game window. Pixels exist
only transiently while a frame is cropped and are neither logged nor uploaded.

## Calibration

Validate manual bounds without editing source:

```bash
geometry-dash-calibrate --backend portal
# monitor crop example:
geometry-dash-calibrate --backend portal --left 100 --top 120 --width 1280 --height 720 --write-local
```

With no dimensions, portal calibration uses the selected window/surface size.
After one validated frame, `--write-local` writes only `config/local.toml`.
Refusing symlinks and paths outside that fixed destination prevents arbitrary
calibration writes. `--sample-player LEFT TOP WIDTH HEIGHT` samples a manually
chosen saturated patch and writes a robust median RGB signature; verify it in
the main local browser preview before relying on it. The legacy standalone
`--preview` option is optional and needs Tk support, but the main app does not.

## Recording and Privacy

The diagnostic frame buffer is disabled by default. It has a fixed in-memory
capacity, a 512 MiB total-memory ceiling, and writes compressed event data only
when an explicit caller invokes its event-write method. Writes are confined to
the active project's `data/frames/` directory, which is ignored by Git.
Telemetry contains counters and confidence, never raw pixels. No frames are
uploaded or shared by this project.

## RemoteDesktop control permission

Capture permission never implies control permission. From a healthy Shadow
session, the user may separately request `org.freedesktop.portal.RemoteDesktop`.
The app requests keyboard device type only and sends only Space keysyms through
the portal notification method. KDE must approve the request every launch. The
session is not persisted; revocation or close releases the key and closes the
portal session. Pointer, touchscreen, clipboard, generic key names, and arbitrary
DBus service/method configuration are absent.

## Shadow telemetry

`geometry-dash-observe --shadow-log session.jsonl` explicitly enables a local
decision log at `data/runs/session.jsonl`. It records player/geometry summaries,
candidate score, recommendation, collision forecast, and confidence; it never
stores raw frames. Absolute paths, traversal outside `data/runs`, and symlinks
are rejected.
