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
        if self.mode == 'VISUALIZATION_DEMO':
            # Keep the developer-only fixture deterministic regardless of the
            # hardware-tuned inference cadence used for real sources.
            self.sample_fps = 10.
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
        self._live_buffer = deque()
        self._live_buffer_bytes = 0
        self._live_overlay_buffer = deque()
        self._replay_frames = []
        self._replay_overlays = []
        self._live_playback_position = None
        self._live_playback_anchor = 0.
        self._live_playback_started = 0.
        self._replay_start = None
        self._replay_end = None
        self._reviewing = False
        self._seek_request = None
        self._analytics_reset_pending = False
        self.analysis_generation = 0
        self._last_analysis_media_timestamp = None
        self._track_id_namespace = 0
        self._display_track_ids: dict[int, int] = {}
        self._next_display_track_id = 1
        self._display_times = deque(maxlen=61)
        self._detection_times = deque(maxlen=31)
        self.analysis_fps = 0.
        if self.reader:
            preview = self.reader.read(0)
            if preview is not None:
                self._publish_frame(preview, 0, 0.)

    @property
    def seekable(self):
        if not self.reader or self.cache:
            return False
        if self.reader.is_live:
            with self.frame_lock:
                return len(self._live_buffer) > 1
        return bool(self.reader.duration)

    @property
    def analysis_paused(self):
        return bool(self.reader and not self.reader.is_live and (self.playback_paused or self._reviewing))

    @property
    def playback_bounds(self):
        if not self.reader:
            return 0., 0.
        if not self.reader.is_live:
            return 0., float(self.reader.duration or 0.)
        with self.frame_lock:
            if not self._live_buffer:
                return 0., 0.
            return float(self._live_buffer[0][0]), float(self._live_buffer[-1][0])

    @property
    def replaying(self):
        return self._replay_start is not None and self._replay_end is not None

    @property
    def timeline_bounds(self):
        if self.replaying:
            return float(self._replay_start), float(self._replay_end)
        return self.playback_bounds

    def _playback_position(self):
        start, end = self.playback_bounds
        if not self.reader or not self.reader.is_live:
            return min(max(start, self.latest_timestamp), end)
        with self.playback_lock:
            if self._live_playback_position is None:
                return end
            position = self._live_playback_position
            if not self.playback_paused:
                position = self._live_playback_anchor + time.monotonic() - self._live_playback_started
            if self.replaying:
                clip_start, clip_end = self._replay_start, self._replay_end
                if position >= clip_end:
                    duration = max(.001, clip_end - clip_start)
                    position = clip_start + (position - clip_start) % duration
                    self._live_playback_position = position
                    self._live_playback_anchor = position
                    self._live_playback_started = time.monotonic()
                return min(max(clip_start, position), clip_end)
            return min(max(start, position), end)

    @property
    def playback_position(self):
        return self._playback_position()

    @property
    def at_live_edge(self):
        if not self.reader or not self.reader.is_live:
            return False
        _, end = self.playback_bounds
        with self.playback_lock:
            return self._live_playback_position is None or (self._replay_end is None and not self.playback_paused and self._playback_position() >= end - .25)

    @property
    def display_jpeg(self):
        if not self.reader or not self.reader.is_live:
            return self.jpeg
        position = self._playback_position()
        with self.frame_lock:
            frames = self._replay_frames if self.replaying and self._replay_frames else self._live_buffer
            if not frames:
                return self.jpeg
            return min(frames, key=lambda item: abs(item[0] - position))[1]

    @property
    def replay_tracks(self):
        if not self.reader or not self.reader.is_live or not self.replaying:
            return None
        position = self._playback_position()
        with self.frame_lock:
            overlays = self._replay_overlays if self._replay_overlays else self._live_overlay_buffer
            if not overlays:
                return []
            return min(overlays, key=lambda item: abs(item[0] - position))[1]

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
            if self.reader and self.reader.is_live:
                self._live_buffer.append((timestamp, jpeg))
                if self.replaying and self._replay_start <= timestamp <= self._replay_end:
                    self._replay_frames.append((timestamp, jpeg))
                self._live_buffer_bytes += len(jpeg)
                max_age = max(6., float(settings.live_buffer_seconds))
                max_bytes = max(16 * 1024 * 1024, int(settings.live_buffer_max_megabytes * 1024 * 1024))
                while len(self._live_buffer) > 1 and (timestamp - self._live_buffer[0][0] > max_age or self._live_buffer_bytes > max_bytes):
                    self._live_buffer_bytes -= len(self._live_buffer.popleft()[1])
            self.last_frame_at = now
            self._display_times.append(now)
            if len(self._display_times) > 1:
                elapsed = self._display_times[-1] - self._display_times[0]
                self.display_fps = (len(self._display_times) - 1) / elapsed if elapsed > 0 else 0.

    def _store_live_overlay(self, timestamp: float, tracks: list[dict]):
        if not self.reader or not self.reader.is_live:
            return
        with self.frame_lock:
            self._live_overlay_buffer.append((timestamp, tracks))
            if self.replaying and self._replay_start <= timestamp <= self._replay_end:
                self._replay_overlays.append((timestamp, tracks))
            max_age = max(6., float(settings.live_buffer_seconds))
            while len(self._live_overlay_buffer) > 1 and timestamp - self._live_overlay_buffer[0][0] > max_age:
                self._live_overlay_buffer.popleft()

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
            raise ValueError('Playback controls are not available yet.')
        if self.reader.is_live:
            position = self._playback_position()
            _, end = self.playback_bounds
            with self.playback_lock:
                self.playback_paused = bool(paused)
                if paused:
                    self._live_playback_position = position
                elif not self.replaying and position >= end - .25:
                    self._live_playback_position = None
                else:
                    self._live_playback_position = position
                    self._live_playback_anchor = position
                    self._live_playback_started = time.monotonic()
            return
        with self.playback_lock:
            if not self.replaying:
                self._reviewing = False
            self.playback_paused = bool(paused)

    def seek(self, seconds: float):
        if not self.seekable:
            raise ValueError('This video does not provide a seekable timeline.')
        if self.reader.is_live:
            start, end = self.timeline_bounds
            target = min(max(start, float(seconds)), end)
            with self.playback_lock:
                if not self.replaying and target >= end - .25 and not self.playback_paused:
                    self._live_playback_position = None
                else:
                    self._live_playback_position = target
                    self._live_playback_anchor = target
                    self._live_playback_started = time.monotonic()
            return target
        duration = float(self.reader.duration)
        seconds = min(max(0., float(seconds)), max(0., duration - 1 / self.reader.fps))
        target = max(0, round(seconds * self.reader.fps))
        done = Event()
        result = {}
        with self.playback_lock:
            was_paused = self.playback_paused
            is_replay_seek = self.replaying
            if not is_replay_seek:
                self._reviewing = False
            # Freeze display advancement and inference while the reader moves.
            # This prevents the playback loop from racing past a remote seek.
            self.playback_paused = True
            if self._seek_request is not None:
                self._seek_request[2]['error'] = 'A newer seek replaced this request.'
                self._seek_request[1].set()
            self._seek_request = (target, done, result)
            self.source_ended = False
            self.completed = False
            if not is_replay_seek:
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

    def replay_window(self, timestamp: float, before: float = 3., after: float = 3.):
        if not self.seekable:
            raise ValueError('This source does not provide a replayable timeline.')
        event_time = float(timestamp)
        start_bound, end_bound = self.playback_bounds
        if self.reader.is_live and not start_bound <= event_time <= end_bound + .5:
            raise ValueError('This event is outside the available live replay buffer.')
        start = max(start_bound, event_time - max(0., before))
        recorded_end = max(0., float(self.reader.duration or 0.) - 1 / self.reader.fps)
        end = min(recorded_end, event_time + max(0., after)) if not self.reader.is_live else event_time + max(0., after)
        if self.reader.is_live:
            with self.frame_lock:
                replay_frames = [item for item in self._live_buffer if start <= item[0] <= end]
                replay_overlays = [item for item in self._live_overlay_buffer if start <= item[0] <= end]
            with self.playback_lock:
                self._replay_start = start
                self._replay_end = end
                self._replay_frames = replay_frames
                self._replay_overlays = replay_overlays
                self._live_playback_position = start
                self._live_playback_anchor = start
                self._live_playback_started = time.monotonic()
                self.playback_paused = False
            return start, end
        with self.playback_lock:
            self._replay_start = start
            self._replay_end = end
            self._reviewing = True
        try:
            self.seek(start)
        except ValueError:
            with self.playback_lock:
                self._replay_start = None
                self._replay_end = None
                self._reviewing = False
            raise
        with self.playback_lock:
            self.playback_paused = False
        return start, end

    def stop_replay(self):
        with self.playback_lock:
            if not self.replaying:
                return
            self._replay_start = None
            self._replay_end = None
            self._reviewing = False
            self._replay_frames = []
            self._replay_overlays = []
            if self.reader and self.reader.is_live:
                self._live_playback_position = None
                self.playback_paused = False
            else:
                self.playback_paused = True

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

    def _tracked_observations(self, tracked, namespace: int = 0):
        """Attach compact UI IDs without weakening collision-safe tracker IDs."""
        observations = []
        for item in tracked:
            track_id = int(item.id) + namespace
            display_id = self._display_track_ids.get(track_id)
            if display_id is None:
                display_id = self._next_display_track_id
                self._display_track_ids[track_id] = display_id
                self._next_display_track_id += 1
            observations.append({
                'id': track_id, 'display_id': display_id,
                'bbox': item.bbox, 'confidence': item.confidence,
            })
        return observations

    def _reader_loop(self):
        frame_id = max(0, self.latest_frame_id) + 1
        started = time.monotonic() - frame_id / self.reader.fps
        consecutive_failures = 0
        while not self.stop_reader_event.is_set():
            with self.playback_lock:
                seek_request = self._seek_request
                self._seek_request = None
                paused = self.playback_paused and not self.reader.is_live
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
                if not self.reader.is_live:
                    with self.playback_lock:
                        if self.replaying and timestamp >= self._replay_end:
                            target = max(0, round(self._replay_start * self.reader.fps))
                            replay_frame = self.reader.read(target)
                            if replay_frame is not None:
                                frame_id = target + 1
                                started = time.monotonic() - frame_id / self.reader.fps
                                self._publish_frame(replay_frame, target, target / self.reader.fps)
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
        if self.analysis_paused:
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
        if self.analysis_paused:
            return None
        with self.analytics_lock:
            # Analysis time measures footage actually observed. Seeking does not
            # add or subtract time, which keeps behavior timestamps monotonic and
            # preserves accumulated statistics across timeline jumps.
            elapsed = 0. if self._last_analysis_media_timestamp is None else max(0., media_timestamp - self._last_analysis_media_timestamp)
            analysis_timestamp = self.timestamp + elapsed
            tracked = self.tracker.update(detections, analysis_timestamp)
            namespaced = self._tracked_observations(tracked, self._track_id_namespace)
            self.engine.update(namespaced, analysis_timestamp, media_timestamp)
            overlay_tracks = [track.serialize(True) for track in self.engine.tracks.values()]
            overlay_tracks += [
                track.serialize(False) for track in self.engine.archived.values()
                if analysis_timestamp - track.last_seen <= 2.
            ]
            self.frame, self.timestamp = frame_id, analysis_timestamp
            self._last_analysis_media_timestamp = media_timestamp
        self._store_live_overlay(media_timestamp, overlay_tracks)
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
        tracked = self._tracked_observations(self.tracker.update(detections, timestamp))
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
        if self.seekable and self.reader and not self.reader.is_live:
            self.playback_paused = True
        with self.analytics_lock:
            self.engine.finish(self.timestamp)

    def close(self):
        self.stop_reader_event.set()
        if self.reader:
            self.reader.close()
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=2)
