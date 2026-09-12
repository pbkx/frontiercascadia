"""Small detector-neutral adapter around supervision's ByteTrack implementation."""

from dataclasses import dataclass
import math

import numpy as np
import supervision as sv

from ..detection.base import Detection


@dataclass(frozen=True)
class TrackedDetection:
    id: int
    bbox: list[float]
    confidence: float


class Tracker:
    """Associate fish detections; outputs retain normalized image coordinates.

    ByteTrack uses high-confidence detections to initiate tracks and associates
    lower-confidence observations with existing tracks. No detector-specific data
    enters this adapter. Missing observations advance ByteTrack's lost-track age.
    """

    _SCALE = 1000.0

    def __init__(self, sample_fps: float = 10):
        self.sample_fps = max(1.0, float(sample_fps))
        self._tracker = sv.ByteTrack(
            track_activation_threshold=0.35,
            lost_track_buffer=45,
            minimum_matching_threshold=0.8,
            frame_rate=max(1, round(self.sample_fps)),
            minimum_consecutive_frames=1,
        )
        self._last_timestamp: float | None = None

    def update(self, detections: list[Detection], timestamp: float) -> list[TrackedDetection]:
        if not math.isfinite(timestamp):
            raise ValueError('Tracking timestamps must be finite.')
        if self._last_timestamp is not None and timestamp < self._last_timestamp:
            raise ValueError('Tracking timestamps must be monotonic; start a new tracker when seeking.')
        # Account for skipped inference frames without retaining IDs indefinitely.
        if self._last_timestamp is not None:
            missed = min(120, max(0, round((timestamp - self._last_timestamp) * self.sample_fps) - 1))
            for _ in range(missed):
                self._tracker.update_with_detections(sv.Detections.empty())
        self._last_timestamp = timestamp
        boxes, confidence = [], []
        for detection in detections:
            if detection.class_name.lower() != 'fish':
                continue
            values = [*detection.bbox, detection.confidence]
            if not all(math.isfinite(value) for value in values):
                continue
            box = np.clip(detection.bbox, 0, 1)
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            boxes.append(box * self._SCALE)
            confidence.append(min(1.0, max(0.0, detection.confidence)))
        observations = (
            sv.Detections(
                xyxy=np.asarray(boxes, dtype=np.float32),
                confidence=np.asarray(confidence, dtype=np.float32),
                class_id=np.zeros(len(boxes), dtype=int),
            )
            if boxes else sv.Detections.empty()
        )
        tracked = self._tracker.update_with_detections(observations)
        if tracked.tracker_id is None:
            return []
        return [
            TrackedDetection(int(track_id), (box / self._SCALE).tolist(), float(score))
            for box, score, track_id in zip(tracked.xyxy, tracked.confidence, tracked.tracker_id)
        ]
