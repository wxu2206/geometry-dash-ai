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

Do not attach sensitive recordings, tokens, personal data, or weaponized payloads
to public reports.

