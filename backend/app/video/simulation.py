import math
from ..detection.base import Detection


def synthetic_fish(timestamp: float) -> list[dict]:
    """Deterministic illustrative paths, never detector results or Issaquah measurements.

    Every 48 seconds: ordinary passages, an approach/retreat/re-approach,
    a downstream fish, and a fish dwelling near the gate.
    """
    cycle = int(timestamp // 48)
    fish = []
    for batch in range(max(0, cycle - 1), cycle + 1):
        for i in range(10):
            age = timestamp - (batch * 48 + i * 2.6)
            if age < 0:
                continue
            kind = i % 5
            speed = 0.032 + (i % 3) * .004
            heading = 0.
            if kind == 2:
                # Meaningful approach, retreat, then a second upstream attempt.
                if age < 12:
                    x = .13 + .037 * age
                elif age < 19:
                    x = .574 - .031 * (age - 12)
                    heading = math.pi
                else:
                    x = .357 + .043 * (age - 19)
            elif kind == 3:
                x = 1.02 - speed * age
                heading = math.pi
            elif kind == 4:
                x = .06 + .047 * min(age, 10.8)
                if age > 22:
                    x += .043 * (age - 22)
                elif age > 10.8:
                    x += .002 * math.sin(age)
            else:
                x = (.32 if i == 0 else -.06) + speed * age
            if not -.07 <= x <= 1.07:
                continue
            y = .25 + (i % 4) * .142 + .026 * math.sin(age * .28 + i)
            w = .103 + .011 * (i % 3)
            h = .045 + .005 * (i % 2)
            box = [max(0., x - w / 2), max(0., y - h / 2), min(1., x + w / 2), min(1., y + h / 2)]
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            fish.append({'id': batch * 10 + i + 1, 'bbox': box, 'heading': heading, 'x': x, 'y': y, 'confidence': .92 + .025 * math.sin(i + age * .1)})
    return fish


def synthetic_detections(timestamp: float) -> tuple[list[Detection], list[dict]]:
    fish = synthetic_fish(timestamp)
    return [Detection(*f['bbox'], f['confidence']) for f in fish], fish
