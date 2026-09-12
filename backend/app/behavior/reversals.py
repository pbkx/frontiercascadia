"""Persistent, confident U-turn heuristic; thresholds are not biological labels."""

from dataclasses import dataclass
import math

from .trajectories import dot, subtract


@dataclass
class ReversalState:
    origin: tuple
    heading: tuple | None = None
    extreme: tuple | None = None
    candidate_since: float | None = None
    candidate_frames: int = 0

    def update(self, point, velocity, confidence, timestamp, threshold):
        speed = math.hypot(*velocity)
        if confidence < 0.55 or speed < 0.015:
            self.candidate_since, self.candidate_frames = None, 0
            return None
        heading = (velocity[0] / speed, velocity[1] / speed)
        if self.heading is None:
            if math.dist(self.origin, point) >= threshold:
                self.heading, self.extreme = heading, point
            return None
        advance = dot(subtract(point, self.extreme), self.heading)
        if advance > 0:
            self.extreme = point
        # At least a 120-degree change excludes common bends and lateral motion.
        if dot(heading, self.heading) > -0.5:
            self.candidate_since, self.candidate_frames = None, 0
            return None
        if self.candidate_since is None:
            self.candidate_since = timestamp
        self.candidate_frames += 1
        retreat = -dot(subtract(point, self.extreme), self.heading)
        if retreat < threshold or self.candidate_frames < 3 or timestamp - self.candidate_since < 0.25:
            return None
        location = self.extreme
        self.heading, self.extreme, self.origin = heading, point, point
        self.candidate_since, self.candidate_frames = None, 0
        return list(location)
