from __future__ import annotations

from collections import deque
from pathlib import Path
from threading import Event, RLock, Thread
import time

import cv2

from ..behavior import BehaviorEngine
from ..config import settings
from ..detection.base import DetectorUnavailable
from ..detection.factory import create_detector
from ..tracking import Tracker
from .simulation import synthetic_detections, synthetic_fish
from .sources import CachedPlayback, StreamSource, VideoReader


class VideoProcessor:
    """Display frames independently while inference always consumes the newest frame."""

    def __init__(self, video: Path | str | StreamSource | None = None, cache: Path | None = None, calibration: dict | None = None):
        self.video = video
        self.reader = VideoReader(video) if video else None
        self.cache = None
        self.detector = None
        self.detector_error = None
        self.stream_error = None
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
                # Video remains available even when local inference is not.
                self.detector_error = str(exc)
        self.tracker = Tracker(sample_fps=self.sample_fps, detection_threshold=settings.confidence_threshold)
        self.engine = BehaviorEngine(calibration=calibration, sample_fps=self.sample_fps)
        self.analytics_lock = RLock()
        self.frame_lock = RLock()
        self.index = 0
        self.frame = 0
        self.timestamp = 0.
        self.simulation_fish = synthetic_fish(0) if not video else []
        self.jpeg = None
        self.completed = False
        self.source_ended = False
        self.reconnecting = False
        self.reconnect_attempts = 0
        self.display_fps = 0.
        self.latest_frame = None
        self.latest_frame_id = -1
        self.latest_timestamp = 0.
        self.processed_frame_id = -1
        self.reader_thread: Thread | None = None
        self.stop_reader_event = Event()
        self._display_times = deque(maxlen=61)
        self._detection_times = deque(maxlen=31)
        self.analysis_fps = 0.
        if self.reader:
            preview = self.reader.read(0)
            if preview is not None:
                self._publish_frame(preview, 0, 0.)

    @property
    def error(self):
        return self.stream_error or self.detector_error

    @error.setter
    def error(self, value):
        self.stream_error = value

    @staticmethod
    def encode(frame) -> bytes:
        h, w = frame.shape[:2]
        if w > 1600:
            frame = cv2.resize(frame, (1600, round(h * 1600 / w)))
        ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if not ok:
            raise ValueError('Could not encode video frame.')
        return encoded.tobytes()

    def _publish_frame(self, frame, frame_id: int, timestamp: float):
        jpeg = self.encode(frame)
        now = time.monotonic()
        with self.frame_lock:
            self.latest_frame = frame
            self.latest_frame_id = frame_id
            self.latest_timestamp = timestamp
            self.jpeg = jpeg
            self._display_times.append(now)
            if len(self._display_times) > 1:
                elapsed = self._display_times[-1] - self._display_times[0]
                self.display_fps = (len(self._display_times) - 1) / elapsed if elapsed > 0 else 0.

    def start_reader(self):
        if not self.reader or self.cache or self.mode == 'VISUALIZATION_DEMO':
            return
        if self.reader_thread and self.reader_thread.is_alive():
            return
        self.stop_reader_event.clear()
        self.source_ended = False
        self.reader_thread = Thread(target=self._reader_loop, name='salmonsight-video-reader', daemon=True)
        self.reader_thread.start()

    def _reader_loop(self):
        frame_id = max(0, self.latest_frame_id) + 1
        started = time.monotonic() - frame_id / self.reader.fps
        consecutive_failures = 0
        while not self.stop_reader_event.is_set():
            # HLS demuxers can expose a whole downloaded segment immediately.
            # Pace both files and streams to source time instead of racing
            # through buffered live segments at hundreds of frames per second.
            due = started + frame_id / self.reader.fps
            delay = due - time.monotonic()
            if delay > 0 and self.stop_reader_event.wait(delay):
                break
            frame = self.reader.read_next()
            if frame is not None:
                consecutive_failures = 0
                self.reconnecting = False
                self.stream_error = None
                timestamp = time.monotonic() - started if self.reader.is_live else frame_id / self.reader.fps
                self._publish_frame(frame, frame_id, timestamp)
                frame_id += 1
                continue
            if not self.reader.is_live:
                self.source_ended = True
                break
            consecutive_failures += 1
            self.reconnecting = True
            self.reconnect_attempts += 1
            if consecutive_failures > settings.stream_reconnect_attempts:
                self.stream_error = 'Unable to connect to this stream. Try again or choose another source.'
                break
            if self.stop_reader_event.wait(min(8., .5 * 2 ** (consecutive_failures - 1))):
                break
            try:
                self.reader.reconnect()
                frame_id = max(frame_id, self.latest_frame_id + 1)
                started = time.monotonic() - frame_id / self.reader.fps
            except (ValueError, OSError):
                continue

    def detect_latest(self):
        """Return True after inference, None while waiting, or False at terminal state."""
        if self.completed or self.detector_error or self.stream_error:
            return False
        with self.frame_lock:
            frame_id = self.latest_frame_id
            if frame_id == self.processed_frame_id or self.latest_frame is None:
                if self.source_ended and frame_id == self.processed_frame_id:
                    self.complete()
                    return False
                return None
            # A single frame reference is enough: reader publishes a new ndarray
            # instead of mutating this one, so there is no growing queue or copy.
            frame = self.latest_frame
            timestamp = self.latest_timestamp
        try:
            detections = self.detector.detect(frame)
        except DetectorUnavailable as exc:
            self.detector_error = str(exc)
            return False
        tracked = self.tracker.update(detections, timestamp)
        with self.analytics_lock:
            self.engine.update(tracked, timestamp)
            self.frame, self.timestamp = frame_id, timestamp
        self.processed_frame_id = frame_id
        self.index += 1
        self._detection_times.append(time.monotonic())
        if len(self._detection_times) > 1:
            elapsed = self._detection_times[-1] - self._detection_times[0]
            self.analysis_fps = (len(self._detection_times) - 1) / elapsed if elapsed > 0 else 0.
        return True

    def step(self) -> bool:
        """Deterministic synchronous path retained for caches, tests and tools."""
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
                self.stream_error = 'Video ended before cached detections. Recompute the demo cache.'
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
                self.detector_error = str(exc)
                return False
        tracked = self.tracker.update(detections, timestamp)
        with self.analytics_lock:
            self.engine.update(tracked, timestamp)
            self.frame, self.timestamp = frame_number, timestamp
            self.jpeg, self.simulation_fish = jpeg, simulation_fish
        self.index += 1
        return True

    def complete(self):
        if self.completed:
            return
        self.completed = True
        with self.analytics_lock:
            self.engine.finish(self.timestamp)

    def close(self):
        self.stop_reader_event.set()
        if self.reader:
            self.reader.close()
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=2)
