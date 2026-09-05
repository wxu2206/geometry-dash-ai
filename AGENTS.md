# Coding Agent Instructions

This project is developed on Bazzite, an immutable Fedora-based Linux system.

## Environment Safety

NEVER USE OR RECOMMEND:

- `sudo`
- `dnf`
- `rpm`
- `rpm-ostree`
- host OS package installation or modification
- privilege escalation
- writes to protected system directories

Use only repository-local tools, Python virtual environments, `pip` inside
`.venv`, and the user's existing NVM-managed Node/npm environment if JavaScript
is necessary. If a required host dependency is unavailable, stop and report it
as a blocker. Do not attempt to install it on the host.

## Git and GitHub Safety

NEVER RUN:

- `git push`
- `gh pr create`
- commands that modify remote branches
- force pushes
- commands that publish releases or merge remote pull requests

The user manually performs every remote GitHub operation. Local inspection,
branches, staging, tests, and descriptive commits are allowed. Preserve unrelated
working-tree changes and do not use destructive Git commands without explicit
authorization.

## Project Guardrails

- The agent observes live rendered pixels and uses simulated input only.
- Never read Geometry Dash level files or game memory.
- Never add mods that expose internal state or coordinates.
- Never add timestamp-based Stereo Madness logic or prerecorded click macros.
- Progress percentage is telemetry and must not trigger gameplay actions.
- Keep capture, perception, tracking, physics, planning, control, learning,
  telemetry, UI, configuration, and simulation concerns separated.
- Generated frames, recordings, datasets, logs, calibration output, secrets, and
  large model artifacts must not be committed.
- Live input must default to disabled and must provide an immediate release-all
  emergency stop.

## Development Practice

- Support Python 3.11 and newer; add type hints to production code.
- Prefer deterministic unit tests and synthetic layouts over live-game tests.
- Run tests, linting, and type checking for relevant changes.
- Document architectural or data-format changes.
- Keep CI independent of Geometry Dash and desktop capture/input access.
