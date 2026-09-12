"""Fixed-size spatial accumulators; ratios only appear with a measured baseline."""

import numpy as np

from .dwell import cell


class Heatmaps:
    columns = 20
    rows = 12

    def __init__(self):
        shape = (self.rows, self.columns)
        self.density = np.zeros(shape)
        self.friction = np.zeros(shape)
        self.reversals = np.zeros(shape, dtype=int)
        self.dwell = np.zeros(shape)

    def reversal(self, point):
        key = cell(point, self.columns, self.rows)
        self.reversals[key] += 1
        self.friction[key] += 3.0

    def attempt(self, point):
        self.friction[cell(point, self.columns, self.rows)] += 1.5

    @staticmethod
    def normalized(grid):
        # Square-root scaling exposes weaker trails without inventing counts.
        maximum = float(np.max(grid))
        return (np.sqrt(grid / maximum) if maximum else grid).round(4).tolist()

    def snapshot(self, baseline=None, dwell_threshold=8.0):
        hotspot = None
        # Choose the strongest region that has supporting evidence. An isolated
        # high-weight turn must not hide a different, verified dwell region.
        candidates = np.argsort(self.friction.ravel())[::-1]
        for candidate in candidates:
            row, column = np.unravel_index(candidate, self.friction.shape)
            if self.friction[row, column] <= 0:
                break
            region = (slice(max(0, row - 1), min(self.rows, row + 2)), slice(max(0, column - 1), min(self.columns, column + 2)))
            reversals = int(self.reversals[region].sum())
            dwell = float(self.dwell[region].max())
            if reversals >= 2 or dwell >= dwell_threshold:
                hotspot = {
                    'x': (int(column) + 0.5) / self.columns, 'y': (int(row) + 0.5) / self.rows,
                    'reversals': reversals, 'dwell_seconds': round(dwell, 2),
                    'baseline_ratio': round(dwell / baseline, 2) if baseline and baseline > 0 else None,
                }
                break
        return {
            'density': self.normalized(self.density), 'friction': self.normalized(self.friction),
            'columns': self.columns, 'rows': self.rows, 'hotspot': hotspot,
        }
