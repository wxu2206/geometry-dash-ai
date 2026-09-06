# Security Policy

## Supported Versions

The project is pre-release. Security fixes are provided only for the latest code
on the default branch; older commits and forks are not supported.

## Reporting a Vulnerability

Please do not open a public issue or discussion for a suspected vulnerability.
Use this repository's **GitHub Private Vulnerability Reporting** option under the
Security tab. If that option is unavailable, ask a maintainer through a public
issue for a private reporting channel without including exploit details.

Include the affected version or commit, impact, reproduction conditions, and a
minimal proof of concept when safe. Please avoid public disclosure until a fix
is available and coordinated with the maintainers. You should receive an initial
acknowledgement through GitHub; response and remediation time depend on severity
and maintainer availability.

Relevant issues include, but are not limited to:

- input automation that cannot be stopped or targets unintended applications;
- unsafe screen-capture or synthetic-input permission handling;
- malicious or untrusted model, calibration, telemetry, or dataset files;
- arbitrary file read/write, path traversal, or command execution;
- dependency or build-chain vulnerabilities; and
- accidental exposure of captured frames, credentials, or private logs.

## Alpha security boundaries

Screen capture uses the fixed `org.freedesktop.portal.ScreenCast` endpoint on the
current user's session bus and begins only after the KDE source chooser succeeds.
The approved PipeWire descriptor is passed to a fixed, `shell=False` GStreamer
argument vector. The selected surface is cropped immediately; frames remain local
and diagnostic saving is off by default.

Live input uses only the fixed `org.freedesktop.portal.RemoteDesktop` interface,
requests keyboard capability only, and can emit only bounded Space press/release
events. Permission, arming, and Running are distinct. Stale observations,
confidence loss, portal failure, watchdog expiry, pause, shutdown, completion,
and Emergency Stop release the action and disarm. Portal sessions and tokens are
not persisted or logged.

`geometry-dash-ai stop` writes an owner-only flag under `XDG_RUNTIME_DIR`; no TCP,
UDP, Unix socket listener, or remote endpoint exists. A local `flock` prevents two
live-control owners. Configuration, calibration, history, and diagnostic paths
are fixed beneath project/user runtime locations, reject traversal/symlinks at
their security boundaries, and use non-executable TOML/JSON/JSONL. Pickle and
unsafe dynamic loading are not used.

Do not attach sensitive recordings, tokens, personal data, or weaponized payloads
to public reports.
