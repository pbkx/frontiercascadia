"""Finite line crossings with spatial hysteresis, clearance, and debounce."""

from dataclasses import dataclass
import math

from .trajectories import dot, subtract


class PassageGate:
    def __init__(self, endpoints, upstream):
        self.a, self.b = tuple(endpoints[0]), tuple(endpoints[1])
        self.vector = subtract(self.b, self.a)
        self.length = math.hypot(*self.vector)
        if self.length < 0.01:
            raise ValueError('The passage gate must have two distinct endpoints.')
        self.normal = (-self.vector[1] / self.length, self.vector[0] / self.length)
        self.upstream = upstream
        self.orientation = 1 if dot(self.normal, upstream) >= 0 else -1

    def distance(self, point):
        return dot(subtract(point, self.a), self.normal)

    def approach_distance(self, point):
        return self.distance(point) * self.orientation

    def along(self, point):
        return dot(subtract(point, self.a), self.vector) / (self.length * self.length)

    def intersection(self, start, end):
        d1, d2 = self.distance(start), self.distance(end)
        if abs(d1 - d2) < 1e-12:
            return None
        fraction = d1 / (d1 - d2)
        point = tuple(start[i] + fraction * (end[i] - start[i]) for i in (0, 1))
        if 0 <= fraction <= 1 and 0 <= self.along(point) <= 1:
            return point
        return None


@dataclass
class CrossingState:
    side: int = 0
    anchor: tuple | None = None
    armed: bool = True
    last_crossing: float = -math.inf

    def update(self, point, timestamp, gate):
        distance = gate.distance(point)
        side = 1 if distance > 0.012 else -1 if distance < -0.012 else 0
        if not side:
            return None
        if self.side == 0 or side == self.side:
            if abs(distance) >= 0.04:
                self.armed = True
            self.side, self.anchor = side, point
            return None
        intersection = gate.intersection(self.anchor, point)
        previous = self.anchor
        self.side, self.anchor = side, point
        if intersection is None or not self.armed or timestamp - self.last_crossing < 0.75:
            return None
        projected = dot(subtract(point, previous), gate.upstream)
        if abs(projected) < 0.008:
            return None
        self.armed = False
        self.last_crossing = timestamp
        return {'direction': 'upstream' if projected > 0 else 'downstream', 'timestamp': timestamp, 'position': list(intersection)}
