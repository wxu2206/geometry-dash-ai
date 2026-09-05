# Bazzite Setup

Bazzite is an immutable Fedora-based operating system. Project development must
not alter the host OS.

## Non-Negotiable Constraints

Never use or recommend `sudo`, `dnf`, `rpm`, `rpm-ostree`, host-level package
installation, privilege escalation, or writes to protected system directories.
Do not layer packages into the image. If a required native capture/input library
is missing, stop and report the dependency and impacted feature as a blocker.

## Repository-Local Python Environment

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp config/default.toml config/local.toml
```

Use `python -m pip` only while `.venv` is active. The environment and local config
are ignored by Git. If JavaScript becomes necessary, use only the user's existing
NVM-managed Node/npm environment and repository-local dependencies.

## Headless Development

The simulator, linting, type checks, and unit tests do not need Geometry Dash or
desktop permissions:

```bash
PYTHONPATH=src python -m geometry_dash_ai.simulation --steps 240
python -m pytest
python -m ruff check .
python -m mypy src
```

## Future Live Setup

Wayland/X11 capture and input support will be selected only after detecting what
is already available in the user session. The setup tool will report missing
native capabilities without trying to install them. Screen capture and synthetic
input may require explicit desktop/session permission; grant only the narrowest
permission needed.

Start with `[control].enabled = false`. Select and preview a capture region, verify
that it contains no private desktop content, and test emergency stop and release
behavior before enabling input. Default emergency stop is `F12`.

## Troubleshooting Information

When reporting a blocker, include Bazzite version, desktop session type, Python
version, relevant permission state, the exact repository-local command, and a
sanitized error. Do not share captured personal content or credentials.

