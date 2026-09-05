"""Read-only adapter that visualizes a Phase 2 cube recommendation from perception."""

from __future__ import annotations

from geometry_dash_ai.physics.cube import CubePhysicsParameters, CubeState
from geometry_dash_ai.planning.cube import CubePlannerConfig, PlanDecision, plan_cube_action
from geometry_dash_ai.vision.models import PlayerMode
from geometry_dash_ai.vision.pipeline import PerceptionSnapshot


def preview_cube_plan(snapshot: PerceptionSnapshot) -> PlanDecision | None:
    """Return what the planner would recommend; this function cannot execute it."""
    player = snapshot.tracked_player
    if (
        snapshot.perception_unreliable
        or snapshot.local_geometry is None
        or player.bounds is None
        or player.mode is not PlayerMode.CUBE
    ):
        return None
    floor_under_player = any(
        floor.start_x <= 0.0 <= floor.end_x for floor in snapshot.local_geometry.floors
    )
    if not floor_under_player:
        return None
    physics = CubePhysicsParameters(
        collision_width=player.bounds.width,
        collision_height=player.bounds.height,
    )
    state = CubeState(
        0.0,
        0.0,
        player.vx,
        -player.vy,
        player.bounds.width,
        player.bounds.height,
        True,
    )
    return plan_cube_action(state, snapshot.local_geometry, physics, CubePlannerConfig())
