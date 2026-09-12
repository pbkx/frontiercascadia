"""An attempt is a meaningful approach, rearmed after a meaningful retreat."""

from dataclasses import dataclass


@dataclass
class AttemptState:
    origin: float
    peak: float
    trough: float
    phase: str = 'idle'

    def update(self, point, direction, gate):
        position = gate.approach_distance(point)
        self.peak = max(self.peak, position)
        self.trough = min(self.trough, position)
        near = -0.22 <= position <= 0.06 and -0.08 <= gate.along(point) <= 1.08
        if self.phase in ('approaching', 'passed'):
            if direction == 'downstream' and self.peak - position >= 0.06:
                self.phase, self.trough = 'retreated', position
            return False
        advance = position - (self.trough if self.phase == 'retreated' else self.origin)
        if near and direction == 'upstream' and advance >= 0.035:
            self.phase, self.peak = 'approaching', position
            return True
        return False

    def crossing_attempt(self):
        new = self.phase != 'approaching'
        self.phase = 'passed'
        return new
