"""Validated, rendering-independent collision geometry.

Coordinates are abstract world units with positive x to the right and positive y
up. An AABB position is its lower-left corner. Spikes are isosceles triangles,
not lethal bounding boxes.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import hypot, isfinite


MAX_GEOMETRY_ITEMS = 1_024
MAX_ABS_COORDINATE = 1_000_000_000.0

Point = tuple[float, float]


def require_finite(name: str, value: float) -> None:
    """Reject booleans, non-numbers, NaN, infinity, and extreme coordinates."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if abs(value) > MAX_ABS_COORDINATE or not isfinite(value):
        raise ValueError(f"{name} must be finite and within supported bounds")


def require_positive(name: str, value: float) -> None:
    require_finite(name, value)
    if value <= 0:
        raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class AABB:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        require_finite("AABB.x", self.x)
        require_finite("AABB.y", self.y)
        require_positive("AABB.width", self.width)
        require_positive("AABB.height", self.height)
        require_finite("AABB.right", self.right)
        require_finite("AABB.top", self.top)

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def top(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> Point:
        return (self.x + self.width / 2.0, self.y + self.height / 2.0)

    def overlaps(self, other: AABB) -> bool:
        return (
            self.x < other.right
            and self.right > other.x
            and self.y < other.top
            and self.top > other.y
        )


@dataclass(frozen=True, slots=True)
class SolidRect:
    bounds: AABB
    obstacle_id: str = "solid"

    def __post_init__(self) -> None:
        if not isinstance(self.bounds, AABB):
            raise ValueError("SolidRect.bounds must be an AABB")
        _validate_id(self.obstacle_id)


@dataclass(frozen=True, slots=True)
class FloorSegment:
    start_x: float
    end_x: float
    height: float = 0.0
    obstacle_id: str = "floor"

    def __post_init__(self) -> None:
        require_finite("FloorSegment.start_x", self.start_x)
        require_finite("FloorSegment.end_x", self.end_x)
        require_finite("FloorSegment.height", self.height)
        if self.end_x <= self.start_x:
            raise ValueError("FloorSegment.end_x must be greater than start_x")
        _validate_id(self.obstacle_id)


@dataclass(frozen=True, slots=True)
class Spike:
    x: float
    base_y: float
    width: float
    height: float
    obstacle_id: str = "spike"

    def __post_init__(self) -> None:
        require_finite("Spike.x", self.x)
        require_finite("Spike.base_y", self.base_y)
        require_positive("Spike.width", self.width)
        require_positive("Spike.height", self.height)
        require_finite("Spike.right", self.x + self.width)
        require_finite("Spike.top", self.base_y + self.height)
        _validate_id(self.obstacle_id)

    @property
    def vertices(self) -> tuple[Point, Point, Point]:
        return (
            (self.x, self.base_y),
            (self.x + self.width / 2.0, self.base_y + self.height),
            (self.x + self.width, self.base_y),
        )


@dataclass(frozen=True, slots=True)
class LocalGeometry:
    floors: tuple[FloorSegment, ...] = ()
    solids: tuple[SolidRect, ...] = ()
    spikes: tuple[Spike, ...] = ()
    death_y: float = -48.0
    uncertainty: float = 0.0

    def __post_init__(self) -> None:
        require_finite("LocalGeometry.death_y", self.death_y)
        require_finite("LocalGeometry.uncertainty", self.uncertainty)
        if not 0.0 <= self.uncertainty <= 1.0:
            raise ValueError("LocalGeometry.uncertainty must be in [0, 1]")
        collections = (
            ("floors", self.floors, FloorSegment),
            ("solids", self.solids, SolidRect),
            ("spikes", self.spikes, Spike),
        )
        count = 0
        for name, values, expected_type in collections:
            if not isinstance(values, tuple):
                raise ValueError(f"LocalGeometry.{name} must be a tuple")
            count += len(values)
            if count > MAX_GEOMETRY_ITEMS:
                raise ValueError(
                    f"local geometry exceeds hard limit of {MAX_GEOMETRY_ITEMS} items"
                )
            if any(not isinstance(value, expected_type) for value in values):
                raise ValueError(f"LocalGeometry.{name} contains malformed geometry")
        if any(self.death_y >= floor.height for floor in self.floors):
            raise ValueError("LocalGeometry.death_y must be below every floor surface")

    @property
    def item_count(self) -> int:
        return len(self.floors) + len(self.solids) + len(self.spikes)

    def nearest(self, x: float, limit: int) -> LocalGeometry:
        """Return at most ``limit`` geometry items nearest the planning position."""
        require_finite("planning x", x)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("geometry limit must be a positive integer")
        if limit > MAX_GEOMETRY_ITEMS:
            raise ValueError(f"geometry limit cannot exceed {MAX_GEOMETRY_ITEMS}")
        if self.item_count <= limit:
            return self

        tagged: list[tuple[float, int, str, object]] = []
        tagged.extend(
            (_interval_distance(x, floor.start_x, floor.end_x), index, "floor", floor)
            for index, floor in enumerate(self.floors)
        )
        tagged.extend(
            (_interval_distance(x, solid.bounds.x, solid.bounds.right), index, "solid", solid)
            for index, solid in enumerate(self.solids)
        )
        tagged.extend(
            (abs(spike.x - x), index, "spike", spike)
            for index, spike in enumerate(self.spikes)
        )
        selected = sorted(tagged, key=lambda item: (item[0], item[2], item[1]))[:limit]
        floors = tuple(item for _, _, kind, item in selected if kind == "floor")
        solids = tuple(item for _, _, kind, item in selected if kind == "solid")
        spikes = tuple(item for _, _, kind, item in selected if kind == "spike")
        return LocalGeometry(
            floors=tuple(item for item in floors if isinstance(item, FloorSegment)),
            solids=tuple(item for item in solids if isinstance(item, SolidRect)),
            spikes=tuple(item for item in spikes if isinstance(item, Spike)),
            death_y=self.death_y,
            uncertainty=self.uncertainty,
        )


def _validate_id(value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError("obstacle_id must be a non-empty string of at most 128 characters")


def _interval_distance(value: float, start: float, end: float) -> float:
    return max(start - value, value - end, 0.0)


def spike_intersects_aabb(spike: Spike, box: AABB) -> bool:
    """Test triangle/AABB overlap using a Minkowski-expanded convex polygon."""
    return _point_in_convex_polygon(box.center, _inflated_spike(spike, box.width, box.height))


def swept_spike_collision_time(spike: Spike, start: AABB, end: AABB) -> float | None:
    """Return the first normalized collision time for a linearly swept AABB."""
    if start.width != end.width or start.height != end.height:
        raise ValueError("swept AABBs must have identical dimensions")
    polygon = _inflated_spike(spike, start.width, start.height)
    return _segment_polygon_entry(start.center, end.center, polygon)


def aabb_distance(first: AABB, second: AABB) -> float:
    """Return Euclidean separation between two closed axis-aligned boxes."""
    dx = max(first.x - second.right, second.x - first.right, 0.0)
    dy = max(first.y - second.top, second.y - first.top, 0.0)
    return hypot(dx, dy)


def spike_distance(spike: Spike, box: AABB) -> float:
    """Return conservative Euclidean distance between a spike triangle and AABB."""
    if spike_intersects_aabb(spike, box):
        return 0.0
    rectangle = (
        (box.x, box.y),
        (box.right, box.y),
        (box.right, box.top),
        (box.x, box.top),
    )
    triangle = spike.vertices
    distances = [
        _point_segment_distance(point, start, end)
        for point in rectangle
        for start, end in _polygon_edges(triangle)
    ]
    distances.extend(
        _point_segment_distance(point, start, end)
        for point in triangle
        for start, end in _polygon_edges(rectangle)
    )
    return min(distances)


def conservative_spike_clearance(spike: Spike, box: AABB) -> float:
    """Return cheap conservative clearance to a spike's bounding rectangle."""
    dx = max(box.x - (spike.x + spike.width), spike.x - box.right, 0.0)
    dy = max(box.y - (spike.base_y + spike.height), spike.base_y - box.top, 0.0)
    return hypot(dx, dy)


@lru_cache(maxsize=4_096)
def _inflated_spike(spike: Spike, width: float, height: float) -> tuple[Point, ...]:
    half_width = width / 2.0
    half_height = height / 2.0
    offsets = (
        (-half_width, -half_height),
        (-half_width, half_height),
        (half_width, -half_height),
        (half_width, half_height),
    )
    points = [
        (vertex[0] + offset[0], vertex[1] + offset[1])
        for vertex in spike.vertices
        for offset in offsets
    ]
    return _convex_hull(points)


def _convex_hull(points: list[Point]) -> tuple[Point, ...]:
    unique = sorted(set(points))
    if len(unique) <= 1:
        return tuple(unique)

    def cross(origin: Point, first: Point, second: Point) -> float:
        return (first[0] - origin[0]) * (second[1] - origin[1]) - (
            first[1] - origin[1]
        ) * (second[0] - origin[0])

    lower: list[Point] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[Point] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return tuple(lower[:-1] + upper[:-1])


def _point_in_convex_polygon(point: Point, polygon: tuple[Point, ...]) -> bool:
    signs: list[bool] = []
    for start, end in _polygon_edges(polygon):
        cross = (end[0] - start[0]) * (point[1] - start[1]) - (
            end[1] - start[1]
        ) * (point[0] - start[0])
        if abs(cross) > 1e-9:
            signs.append(cross > 0)
    return not signs or all(sign == signs[0] for sign in signs)


def _segment_polygon_entry(start: Point, end: Point, polygon: tuple[Point, ...]) -> float | None:
    if _point_in_convex_polygon(start, polygon):
        return 0.0
    direction = (end[0] - start[0], end[1] - start[1])
    entries: list[float] = []
    for edge_start, edge_end in _polygon_edges(polygon):
        edge = (edge_end[0] - edge_start[0], edge_end[1] - edge_start[1])
        denominator = direction[0] * edge[1] - direction[1] * edge[0]
        if abs(denominator) <= 1e-12:
            continue
        offset = (edge_start[0] - start[0], edge_start[1] - start[1])
        movement_t = (offset[0] * edge[1] - offset[1] * edge[0]) / denominator
        edge_t = (offset[0] * direction[1] - offset[1] * direction[0]) / denominator
        if -1e-9 <= movement_t <= 1.0 + 1e-9 and -1e-9 <= edge_t <= 1.0 + 1e-9:
            entries.append(max(0.0, min(1.0, movement_t)))
    if entries:
        return min(entries)
    return 1.0 if _point_in_convex_polygon(end, polygon) else None


def _polygon_edges(polygon: tuple[Point, ...]) -> tuple[tuple[Point, Point], ...]:
    return tuple(
        (polygon[index], polygon[(index + 1) % len(polygon)])
        for index in range(len(polygon))
    )


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return hypot(point[0] - start[0], point[1] - start[1])
    projection = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared
    projection = max(0.0, min(1.0, projection))
    nearest = (start[0] + projection * dx, start[1] + projection * dy)
    return hypot(point[0] - nearest[0], point[1] - nearest[1])
