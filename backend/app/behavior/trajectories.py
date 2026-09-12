"""Bounded trajectory storage and smoothed motion in image-width units/second."""

from collections import deque
from dataclasses import dataclass, field
import math


def centroid(bbox):
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def subtract(a, b):
    return a[0] - b[0], a[1] - b[1]


@dataclass
class Track:
    id: int
    bbox: list[float]
    confidence: float
    first_seen: float
    last_seen: float
    history_length: int
    # `id` remains the collision-safe tracker key. `display_id` is the compact,
    # session-scoped number shown to people and never participates in matching.
    display_id: int | None = None
    point: tuple[float, float] = field(init=False)
    history: deque = field(init=False)
    motion: deque = field(default_factory=lambda: deque(maxlen=30))
    velocity: tuple[float, float] = (0.0, 0.0)
    direction: str = 'uncertain'
    distance_traveled: float = 0.0
    reversals: int = 0
    reversal_locations: deque = field(default_factory=lambda: deque(maxlen=60))
    dwell_time: float = 0.0
    residence: dict = field(default_factory=dict)
    gate_crossings: deque = field(default_factory=lambda: deque(maxlen=60))
    attempts: int = 0
    status: str = 'ACTIVE'
    flags: set = field(default_factory=set)
    passage_seconds: float | None = None
    entered: bool = False
    observed_seconds: float = 0.0

    def __post_init__(self):
        self.point = centroid(self.bbox)
        self.history = deque(maxlen=max(2, self.history_length))
        self.history.append([*self.point, self.first_seen])
        self.motion.append([*self.point, self.first_seen])

    def move(self, bbox, confidence, timestamp, upstream):
        previous = self.point
        elapsed = timestamp - self.last_seen
        self.bbox, self.confidence = list(bbox), confidence
        self.point = centroid(bbox)
        if elapsed <= 0:
            return previous, 0.0
        self.distance_traveled += math.dist(previous, self.point)
        self.observed_seconds += elapsed
        self.last_seen = timestamp
        self.history.append([*self.point, timestamp])
        self.motion.append([*self.point, timestamp])
        while len(self.motion) > 2 and self.motion[0][2] < timestamp - 0.65:
            self.motion.popleft()
        # Linear regression is insensitive to individual frame-to-frame jitter.
        if len(self.motion) >= 3 and timestamp - self.motion[0][2] >= 0.18:
            mean_t = sum(p[2] for p in self.motion) / len(self.motion)
            variance = sum((p[2] - mean_t) ** 2 for p in self.motion)
            mean_xy = [sum(p[axis] for p in self.motion) / len(self.motion) for axis in (0, 1)]
            slope = [sum((p[2] - mean_t) * (p[axis] - mean_xy[axis]) for p in self.motion) / variance for axis in (0, 1)]
            alpha = 1 - math.exp(-elapsed / 0.16)
            self.velocity = tuple(alpha * slope[axis] + (1 - alpha) * self.velocity[axis] for axis in (0, 1))
        projected = dot(self.velocity, upstream)
        self.direction = 'upstream' if projected > 0.015 else 'downstream' if projected < -0.015 else 'uncertain'
        return previous, elapsed

    def serialize(self, active):
        return {
            'id': self.id, 'display_id': self.display_id if self.display_id is not None else self.id,
            'bbox': self.bbox, 'centroid': list(self.point),
            'confidence': self.confidence, 'first_seen': self.first_seen, 'last_seen': self.last_seen,
            'trajectory': list(self.history), 'smoothed_velocity': list(self.velocity),
            'velocity': math.hypot(*self.velocity), 'direction': self.direction,
            'distance_traveled': self.distance_traveled, 'time_observed': self.observed_seconds,
            'reversals': self.reversals, 'reversal_locations': list(self.reversal_locations),
            'dwell_time': self.dwell_time, 'gate_crossings': list(self.gate_crossings),
            'attempts': self.attempts, 'status': self.status, 'flags': sorted(self.flags),
            'active': active, 'passage_seconds': self.passage_seconds,
        }
