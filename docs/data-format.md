# Data Format

## Principles

Record enough context to reproduce perception and prediction failures without
continuously saving full-rate video. Runtime data is local, potentially private,
and ignored by Git.

## Directory Layout

```text
data/
  runs/<run-id>/             Telemetry and run summaries
  frames/<run-id>/           Sampled and event-preserved frames
  models/                    Generated model artifacts
  calibration/              Machine-local fitted parameters
```

Run IDs should use a UTC timestamp plus random suffix, not personal information.
Writers create directories lazily. Retention and storage budgets will be added
before continuous live recording.

## Telemetry JSON Lines

Phase 1 uses UTF-8 JSON Lines, optionally gzip-compressed. Each line is one event:

```json
{"schema_version":1,"event":"player_state","wall_time":"2026-01-01T00:00:00+00:00","monotonic_ns":123456789,"payload":{"attempt":4,"mode":"cube","x":161.2,"y":244.8,"vx":518.0,"vy":-241.0,"confidence":0.93}}
```

Required envelope fields:

- `schema_version`: integer format version;
- `event`: stable snake-case event name;
- `wall_time`: ISO 8601 UTC timestamp for correlation only;
- `monotonic_ns`: monotonic capture/runtime timestamp used for calculations;
- `payload`: event-specific object.

Planned event names include `attempt_started`, `frame_sample`, `player_state`,
`geometry_state`, `plan_selected`, `collision_predicted`, `mode_changed`,
`death_detected`, `attempt_summary`, `calibration_updated`, and
`level_completed`.

## Death Event Bundle

An attempt summary links recent player states, geometry snapshots, action history,
candidate trajectories, selected predictions, confidence, estimated progress, and
actual outcome. A circular in-memory frame buffer preserves dense frames only for
the configured window around death or another diagnostic event. Routine frames
are sampled every N frames.

## Compatibility and Privacy

Readers must reject unsupported schema versions and validate sizes before loading
arrays or models. Migrations create new files instead of silently rewriting raw
runs. Treat frames and logs as sensitive: crop capture regions carefully, avoid
desktop notifications, and inspect artifacts before sharing. Never deserialize
untrusted executable formats.

