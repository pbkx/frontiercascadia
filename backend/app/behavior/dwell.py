"""Residence time is measured in seconds, independently of inference rate."""

import math


def cell(point, columns=20, rows=12):
    return (min(rows - 1, max(0, int(point[1] * rows))), min(columns - 1, max(0, int(point[0] * columns))))


def residence_segments(start, end, seconds, columns=20, rows=12):
    if seconds <= 0:
        return []
    steps = max(1, math.ceil(max(abs(end[0] - start[0]) * columns, abs(end[1] - start[1]) * rows) * 2))
    result = {}
    for index in range(steps):
        fraction = (index + 0.5) / steps
        point = [start[i] + fraction * (end[i] - start[i]) for i in (0, 1)]
        key = cell(point, columns, rows)
        result[key] = result.get(key, 0.0) + seconds / steps
    return list(result.items())
