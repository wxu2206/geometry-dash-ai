"""Read-only planner presentation and outcome comparison for live observation."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from geometry_dash_ai.planning.cube import PlanDecision
from geometry_dash_ai.vision.pipeline import PerceptionSnapshot
from geometry_dash_ai.vision.planner_preview import preview_cube_plan


@dataclass(frozen=True, slots=True)
class ShadowDecision:
    """A display/telemetry-only planning result; it has no execution method."""

    decision: PlanDecision | None
    frame_index: int
    timestamp_ns: int

    @property
    def recommendation(self) -> str:
        if self.decision is None:
            return "NO RECOMMENDATION"
        if self.decision.jump_delay_frames is None:
            return "NO INPUT"
        return f"JUMP +{self.decision.jump_delay_frames} frames"

    @property
    def timing_robustness(self) -> str:
        if self.decision is None:
            return "0/0 variants safe"
        selected = self.decision.selected_candidate
        safe = sum(selected.timing_variant_survival)
        return f"{safe}/{len(selected.timing_variant_survival)} variants safe"


@dataclass(frozen=True, slots=True)
class ShadowOutcome:
    """Visual-only future comparison for a prior recommendation."""

    recommendation_frame: int
    observed_frame: int
    visually_survived_horizon: bool
    predicted_collision: bool


class ShadowOutcomeComparator:
    """Bounded manual-play comparison; it never observes or hooks input events."""

    def __init__(self, maximum_pending: int = 32) -> None:
        if not 1 <= maximum_pending <= 64:
            raise ValueError("shadow comparison capacity must be within 1..64")
        self._pending: deque[ShadowDecision] = deque(maxlen=maximum_pending)

    def record(self, decision: ShadowDecision) -> None:
        if decision.decision is not None:
            self._pending.append(decision)

    def observe(self, snapshot: PerceptionSnapshot) -> tuple[ShadowOutcome, ...]:
        """Resolve due predictions from visual continuity or a confident visual loss."""
        outcomes: list[ShadowOutcome] = []
        remaining: deque[ShadowDecision] = deque(maxlen=self._pending.maxlen)
        player_lost = (
            snapshot.raw_player is None
            and snapshot.tracked_player.lost_seconds > 0.25
        )
        for decision in self._pending:
            assert decision.decision is not None
            due_ns = int(decision.decision.selected_candidate.trajectory.simulated_duration * 1e9)
            elapsed = snapshot.frame.timestamp_ns - decision.timestamp_ns
            if player_lost or elapsed >= due_ns:
                outcomes.append(
                    ShadowOutcome(
                        decision.frame_index,
                        snapshot.frame.sequence,
                        not player_lost,
                        decision.decision.predicted_collision is not None,
                    )
                )
            else:
                remaining.append(decision)
        self._pending = remaining
        return tuple(outcomes)


def evaluate_shadow_plan(snapshot: PerceptionSnapshot) -> ShadowDecision:
    """Evaluate the cube planner with perception only; never send an action."""
    return ShadowDecision(
        preview_cube_plan(snapshot), snapshot.frame.sequence, snapshot.frame.timestamp_ns
    )


def shadow_payload(snapshot: PerceptionSnapshot, shadow: ShadowDecision) -> dict[str, object]:
    """Return bounded JSON-safe telemetry with no pixel buffer or desktop metadata."""
    player = snapshot.tracked_player
    decision = shadow.decision
    geometry = snapshot.local_geometry
    payload: dict[str, object] = {
        "frame_index": shadow.frame_index,
        "player": {
            "mode": player.mode.value,
            "x": None if player.bounds is None else round(player.bounds.x, 2),
            "y": None if player.bounds is None else round(player.bounds.y, 2),
            "vx": round(player.vx, 2),
            "vy": round(player.vy, 2),
            "confidence": round(player.confidence, 3),
        },
        "geometry": {
            "floors": 0 if geometry is None else len(geometry.floors),
            "solids": 0 if geometry is None else len(geometry.solids),
            "spikes": 0 if geometry is None else len(geometry.spikes),
        },
        "recommendation": shadow.recommendation,
        "perception_unreliable": snapshot.perception_unreliable,
    }
    if decision is not None:
        payload["planner"] = {
            "selected_score": round(decision.selected_score, 3),
            "confidence": round(decision.confidence, 3),
            "all_candidates_unsafe": decision.all_candidates_unsafe,
            "timing_robustness": shadow.timing_robustness,
            "candidate_count": len(decision.evaluated_candidates),
            "predicted_collision": (
                None
                if decision.predicted_collision is None
                else decision.predicted_collision.collision_type.value
            ),
            "candidates": [
                {
                    "label": candidate.candidate.label,
                    "jump_delay_frames": candidate.candidate.jump_delay_frames,
                    "score": round(candidate.total_score, 3),
                    "survived": candidate.trajectory.survived_horizon,
                    "collision": (
                        None
                        if candidate.trajectory.collision is None
                        else candidate.trajectory.collision.collision_type.value
                    ),
                    "robustness": round(candidate.robustness_safe_fraction, 3),
                }
                for candidate in decision.evaluated_candidates
            ],
        }
    return payload


def shadow_outcome_payload(outcome: ShadowOutcome) -> dict[str, object]:
    """Serialize a manual-play comparison without including frames or input data."""
    return {
        "recommendation_frame": outcome.recommendation_frame,
        "observed_frame": outcome.observed_frame,
        "visually_survived_horizon": outcome.visually_survived_horizon,
        "predicted_collision": outcome.predicted_collision,
    }
