from pathlib import Path
import cv2
from threading import RLock
from ..config import settings
from ..detection.factory import create_detector
from ..detection.base import DetectorUnavailable
from ..tracking import Tracker
from ..behavior import BehaviorEngine
from .sources import VideoReader, CachedPlayback
from .simulation import synthetic_detections, synthetic_fish


class VideoProcessor:
    """Identical tracking/analytics for real, cached and illustrative detections."""
    def __init__(self, video: Path | str | None = None, cache: Path | None = None, calibration: dict | None = None):
        self.video = video
        self.reader = VideoReader(video) if video else None
        self.cache = None
        self.detector = None
        self.error = None
        self.warning = None
        self.mode = 'VISUALIZATION_DEMO' if video is None else 'LIVE_INFERENCE'
        self.sample_fps = max(1., min(30., settings.inference_sample_fps))
        if self.reader:
            self.sample_fps = min(self.sample_fps, self.reader.fps)
        if cache:
            try:
                self.cache = CachedPlayback(cache, Path(video))
                self.sample_fps = self.cache.cache.sample_fps
                self.mode = 'PRECOMPUTED_DEMO'
            except (ValueError, OSError):
                self.warning = 'Demo cache invalid or belongs to a different video. Recompute it for this clip.'
        if self.mode == 'LIVE_INFERENCE':
            try:
                self.detector = create_detector()
            except DetectorUnavailable as exc:
                self.error = str(exc)
        self.tracker = Tracker(sample_fps=self.sample_fps)
        self.engine = BehaviorEngine(calibration=calibration, sample_fps=self.sample_fps)
        self.analytics_lock = RLock()
        self.index = 0
        self.frame = 0
        self.timestamp = 0.
        self.simulation_fish = synthetic_fish(0) if not video else []
        self.jpeg = None
        self.completed = False
        if self.reader:
            preview = self.reader.read(0)
            if preview is not None:
                self.jpeg = self.encode(preview)

    @staticmethod
    def encode(frame) -> bytes:
        # Limit transport size; aspect ratio is unchanged, normalized boxes align.
        h, w = frame.shape[:2]
        if w > 1600:
            frame = cv2.resize(frame, (1600, round(h * 1600 / w)))
        ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if not ok:
            raise ValueError('Could not encode video frame.')
        return encoded.tobytes()

    def step(self) -> bool:
        if self.completed or self.error:
            return False
        if self.mode == 'VISUALIZATION_DEMO':
            frame_number = self.index
            timestamp = self.index / self.sample_fps
            detections, simulation_fish = synthetic_detections(timestamp)
            jpeg = None
        elif self.cache:
            sample = self.cache.next()
            if sample is None:
                self.complete()
                return False
            frame_number, timestamp, detections = sample
            video_frame = self.reader.read(frame_number)
            if video_frame is None:
                self.error = 'Video ended before cached detections. Recompute the demo cache.'
                return False
            jpeg = self.encode(video_frame)
            simulation_fish = []
        else:
            frame_number = round(self.index * self.reader.fps / self.sample_fps)
            timestamp = frame_number / self.reader.fps
            frame = self.reader.read(frame_number)
            if frame is None:
                self.complete()
                return False
            jpeg = self.encode(frame)
            simulation_fish = []
            try:
                detections = self.detector.detect(frame)
            except DetectorUnavailable as exc:
                # Freeze this analysis on failure: no invented boxes or zero-count frame.
                self.error = str(exc)
                return False
        tracked = self.tracker.update(detections, timestamp)
        with self.analytics_lock:
            self.engine.update(tracked, timestamp)
            self.frame, self.timestamp = frame_number, timestamp
            self.jpeg, self.simulation_fish = jpeg, simulation_fish
        self.index += 1
        return True

    def complete(self):
        self.completed = True
        with self.analytics_lock:
            self.engine.finish(self.timestamp)

    def close(self):
        if self.reader:
            self.reader.close()
