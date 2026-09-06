# Shadow mode

Shadow is the primary planner-validation mode. It runs after the same capture,
frame validation, detection, tracking, geometry conversion, and confidence gates
used by live planning, but it has no action-backend path in the standalone
observer and sends no input in the application.

Cube shadow output includes every bounded candidate's score and trajectory,
selected delay, collision forecast, landing margin, timing-safe fraction,
all-candidates-unsafe status, and confidence. The view draws a selected cyan
path, gray alternative, green landing, and red collision. Compact explicit JSONL
logs contain timestamp/frame, player state, local geometry counts, candidate
scores, recommendation, collision, and confidence—never pixels.

Ship shadow evaluates the same bounded hold/release sequences used by live mode,
shows HOLD/RELEASE, safety/confidence, and draws the selected short trajectory in
purple with a red terminal collision marker when unsafe. It never dispatches the
first segment while the app is in Shadow.

Manual play comparison is visual: the observer records a recommendation and
later checks whether the player remains visible/survives the short horizon. It
does not hook global input events. Use repeated Shadow runs to validate perception
and physics before requesting any control permission.
