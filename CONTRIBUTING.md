# Contributing

Thanks for helping build Geometry Dash AI. The project favors understandable,
testable visual reasoning over opaque gameplay scripts.

## Development Setup

Use Python 3.11 or newer and a repository-local environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp config/default.toml config/local.toml
```

This project is developed on Bazzite. Never use or recommend `sudo`, `dnf`,
`rpm`, `rpm-ostree`, host package installation, privilege escalation, or host OS
modification. Use `pip` only inside `.venv` and the existing NVM Node/npm
environment only if needed. Report a missing native dependency as a blocker.

## Making Changes

- Keep pull requests focused and explain the user-visible or architectural goal.
- Preserve module boundaries and add type hints to production Python.
- Format and lint with Ruff; use clear names and small, explicit interfaces.
- Document changes to architecture, calibration, planning, or persisted formats.
- Add deterministic tests for new logic and synthetic regression layouts for
  gameplay behavior.
- Do not add level-file readers, memory inspection, internal-state mods,
  hardcoded click timings, or prerecorded gameplay macros.

Run before proposing a change:

```bash
python -m pytest
python -m ruff check .
python -m mypy src
```

Live gameplay checks are expected where relevant, but must be described
separately because they do not run in CI.

## Data, Privacy, and Secrets

Do not commit raw datasets, gameplay recordings, frame dumps, generated model
artifacts, calibration output, logs, credentials, API tokens, or local machine
settings. Use small synthetic fixtures or documented download instructions.
Review staged files before every commit.

## Pull Requests

Describe what changed, why, tests performed, limitations, and any manual game
validation. Include screenshots or debug overlays for meaningful UI/perception
changes. Update relevant documentation and note migrations. Maintainers may ask
for a smaller change if unrelated concerns are bundled together.

Report security issues privately according to [SECURITY.md](SECURITY.md).

