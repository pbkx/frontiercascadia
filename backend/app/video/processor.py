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
        self.calibration = calibration or {}
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
        self.engine = BehaviorEngine(calibration=self.calibration, sample_fps=self.sample_fps)
        self.analytics_lock = RLock()
        self.frame_lock = RLock()
        self.playback_lock = RLock()
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
        self.last_frame_at = 0.
        self.latest_frame = None
        self.latest_frame_id = -1
        self.latest_timestamp = 0.
        self.processed_frame_id = -1
        self.reader_thread: Thread | None = None
        self.stop_reader_event = Event()
        self.playback_paused = False
        self._seek_request = None
        self._analytics_reset_pending = False
        self.analysis_generation = 0
        self._last_analysis_media_timestamp = None
        self._track_id_namespace = 0
        self._display_times = deque(maxlen=61)
        self._detection_times = deque(maxlen=31)
        self.analysis_fps = 0.
        if self.reader:
            preview = self.reader.read(0)
            if preview is not None:
                self._publish_frame(preview, 0, 0.)

    @property
    def seekable(self):
        return bool(self.reader and not self.reader.is_live and not self.cache and self.reader.duration)

    @property
    def display_is_fresh(self):
        """Whether the display has received a frame recently enough to be live."""
        return bool(self.jpeg and self.last_frame_at and time.monotonic() - self.last_frame_at < 2.)

    @property
    def current_display_fps(self):
        return self.display_fps if self.display_is_fresh else 0.

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
            self.last_frame_at = now
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

    def set_playback_paused(self, paused: bool):
        if not self.seekable:
            raise ValueError('Playback controls are available only for recorded video.')
        with self.playback_lock:
            self.playback_paused = bool(paused)

    def seek(self, seconds: float):
        if not self.seekable:
            raise ValueError('This video does not provide a seekable timeline.')
        duration = float(self.reader.duration)
        seconds = min(max(0., float(seconds)), max(0., duration - 1 / self.reader.fps))
        target = max(0, round(seconds * self.reader.fps))
        done = Event()
        result = {}
        with self.playback_lock:
            was_paused = self.playback_paused
            # Freeze display advancement and inference while the reader moves.
            # This prevents the playback loop from racing past a remote seek.
            self.playback_paused = True
            if self._seek_request is not None:
                self._seek_request[2]['error'] = 'A newer seek replaced this request.'
                self._seek_request[1].set()
            self._seek_request = (target, done, result)
            self.source_ended = False
            self.completed = False
            self._analytics_reset_pending = abs(target - self.latest_frame_id) > 1
        try:
            self.start_reader()
            if not done.wait(1) and (not self.reader_thread or not self.reader_thread.is_alive()):
                self.start_reader()
            if not done.wait(14):
                with self.playback_lock:
                    if self._seek_request and self._seek_request[1] is done:
                        self._seek_request = None
                raise ValueError('Unable to seek this video. Try another source or format.')
            if result.get('error'):
                raise ValueError(result['error'])
            return self.latest_timestamp
        finally:
            with self.playback_lock:
                self.playback_paused = was_paused

    def _reset_analytics(self):
        """Start a disconnected tracking segment without discarding observations."""
        with self.analytics_lock:
            # A timeline jump must not connect a fish before the seek to a fish
            # after it. Archive active tracks and restart ByteTrack, while
            # retaining counters, archived trajectories, events, and heatmaps.
            self.engine.finish(self.timestamp)
            self.tracker = Tracker(sample_fps=self.sample_fps, detection_threshold=settings.confidence_threshold)
            self.processed_frame_id = -1
            self.analysis_fps = 0.
            self._detection_times.clear()
            self.analysis_generation += 1
            self._track_id_namespace = self.analysis_generation * 1_000_000
            self._last_analysis_media_timestamp = None
        self._analytics_reset_pending = False

    def _reader_loop(self):
        frame_id = max(0, self.latest_frame_id) + 1
        started = time.monotonic() - frame_id / self.reader.fps
        consecutive_failures = 0
        while not self.stop_reader_event.is_set():
            with self.playback_lock:
                seek_request = self._seek_request
                self._seek_request = None
                paused = self.playback_paused
            if seek_request is not None:
                target, done, result = seek_request
                frame = self.reader.read(target)
                if frame is None:
                    result['error'] = 'Unable to seek this video. Try another source or format.'
                else:
                    frame_id = target + 1
                    started = time.monotonic() - frame_id / self.reader.fps
                    self.source_ended = False
                    self.stream_error = None
                    self._publish_frame(frame, target, target / self.reader.fps)
                done.set()
                continue
            if paused:
                self.stop_reader_event.wait(.04)
                continue
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
            retry_cycle = max(1, settings.stream_reconnect_attempts)
            if consecutive_failures >= retry_cycle:
                self.stream_error = 'Unable to connect to this stream. Try again or choose another source.'
            # A live source must never become permanently stuck on its last
            # decoded frame. Keep retrying at a bounded cadence until frames
            # return or the session is closed.
            retry_delay = min(2., .25 * 2 ** min(consecutive_failures - 1, 3))
            if self.stop_reader_event.wait(retry_delay):
                break
            try:
                # Reopen the current signed media URL first. Refresh it through
                # yt-dlp on the second failure and once per retry cycle. Avoid
                # invoking yt-dlp on every transient failed read.
                refresh = consecutive_failures == 2 or consecutive_failures % retry_cycle == 0
                self.reader.reconnect(refresh=refresh)
                frame_id = max(frame_id, self.latest_frame_id + 1)
                started = time.monotonic() - frame_id / self.reader.fps
            except (ValueError, OSError):
                continue

    def detect_latest(self):
        """Return True after inference, None while waiting, or False at terminal state."""
        if self.completed or self.detector_error or (self.stream_error and not self.reconnecting):
            return False
        if self.playback_paused:
            return None
        if self._analytics_reset_pending:
            self._reset_analytics()
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
            media_timestamp = self.latest_timestamp
        try:
            detections = self.detector.detect(frame)
        except DetectorUnavailable as exc:
            self.detector_error = str(exc)
            return False
        if self.playback_paused:
            return None
        with self.analytics_lock:
            # Analysis time measures footage actually observed. Seeking does not
            # add or subtract time, which keeps behavior timestamps monotonic and
            # preserves accumulated statistics across timeline jumps.
            elapsed = 0. if self._last_analysis_media_timestamp is None else max(0., media_timestamp - self._last_analysis_media_timestamp)
            analysis_timestamp = self.timestamp + elapsed
            tracked = self.tracker.update(detections, analysis_timestamp)
            namespaced = [
                {'id': item.id + self._track_id_namespace, 'bbox': item.bbox, 'confidence': item.confidence}
                for item in tracked
            ]
            self.engine.update(namespaced, analysis_timestamp)
            self.frame, self.timestamp = frame_id, analysis_timestamp
            self._last_analysis_media_timestamp = media_timestamp
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
        if self.seekable:
            self.playback_paused = True
        with self.analytics_lock:
            self.engine.finish(self.timestamp)

    def close(self):
        self.stop_reader_event.set()
        if self.reader:
            self.reader.close()
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=2)
