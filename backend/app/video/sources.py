from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
import hashlib
import threading

import cv2

from ..config import ROOT, settings
from ..detection.base import Detection
from ..models.schemas import DetectionCache


YOUTUBE_HOSTS = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'}
STREAM_SCHEMES = {'http', 'https', 'rtsp'}


@dataclass
class StreamSource:
    """A user-facing URL and the decoder URL resolved from it."""

    original_url: str
    resolved_url: str
    display_name: str
    is_live: bool = True
    is_youtube: bool = False


def is_youtube_url(value: str) -> bool:
    host = (urlparse(value).hostname or '').lower()
    return host in YOUTUBE_HOSTS or host.endswith('.youtube.com')


def resolve_stream(value: str, *, default_name: str | None = None) -> StreamSource:
    """Resolve ordinary YouTube pages and validate direct stream URLs."""

    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme.lower() not in STREAM_SCHEMES or not parsed.netloc:
        raise ValueError('Enter a YouTube, HLS, HTTP, HTTPS, or RTSP stream URL.')
    if not is_youtube_url(value):
        path = parsed.path.lower()
        likely_file = path.endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm'))
        return StreamSource(value, value, default_name or parsed.hostname or 'Video stream', not likely_file, False)
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise ValueError('YouTube support is unavailable because yt-dlp is not installed.') from exc
    options = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'format': 'bestvideo[protocol=m3u8]/bestvideo[protocol=m3u8_native]/bestvideo/best',
        'socket_timeout': 15,
        'retries': 2,
        'extractor_retries': 2,
    }
    try:
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(value, download=False)
    except Exception as exc:
        raise ValueError('Unable to connect to this stream. Try again or choose another source.') from exc
    media_url = info.get('url') if isinstance(info, dict) else None
    if not media_url:
        raise ValueError('Unable to connect to this stream. Try again or choose another source.')
    title = default_name or info.get('title') or 'YouTube live stream'
    live_status = info.get('live_status')
    is_live = bool(info.get('is_live')) or live_status in {'is_live', 'is_upcoming'}
    return StreamSource(value, media_url, str(title), is_live, True)


def video_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def discover_demo() -> tuple[Path | None, Path | None]:
    """Developer-only preprocessed fallback; never selected by the normal UI."""
    candidates = [resolve_path(settings.default_demo_video_path), ROOT / 'data/demo/issaquah.mp4', ROOT / 'data/demo/salmon_demo.mp4']
    for video in candidates:
        if video.is_file():
            caches = [video.with_name(video.stem + '_detections.json'), resolve_path(settings.demo_detections_path)]
            return video, next((p for p in caches if p.is_file()), None)
    return None, None


class VideoReader:
    def __init__(self, source: Path | str | StreamSource):
        self.source = source
        self.lock = threading.RLock()
        self.cap = None
        self.last_frame = -1
        self.is_stream = isinstance(source, StreamSource) or isinstance(source, str) and source.startswith(('http://', 'https://', 'rtsp://'))
        self.is_live = source.is_live if isinstance(source, StreamSource) else self.is_stream
        self._open()

    @property
    def decoder_source(self):
        return self.source.resolved_url if isinstance(self.source, StreamSource) else str(self.source)

    def _open(self):
        decoder = self.decoder_source
        if self.is_stream:
            try:
                cap = cv2.VideoCapture(decoder, cv2.CAP_FFMPEG, [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 12000,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC, 12000,
                ])
            except (TypeError, cv2.error):
                cap = cv2.VideoCapture(decoder, cv2.CAP_FFMPEG)
        else:
            cap = cv2.VideoCapture(decoder)
        if not cap.isOpened():
            cap.release()
            message = 'Unable to connect to this stream. Try again or choose another source.' if self.is_stream else 'Cannot decode this video. Use an MP4 with H.264 video or another OpenCV-compatible codec.'
            raise ValueError(message)
        self.cap = cap
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 30.
        if not 0 < self.fps < 1000:
            self.fps = 30.
        self.total_frames = max(0, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
        self.last_frame = -1

    def read(self, frame_number: int):
        with self.lock:
            if frame_number <= self.last_frame or frame_number - self.last_frame > 90:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            else:
                for _ in range(frame_number - self.last_frame - 1):
                    if not self.cap.grab():
                        return None
            ok, frame = self.cap.read()
            self.last_frame = frame_number
            return frame if ok else None

    def read_next(self):
        with self.lock:
            ok, frame = self.cap.read()
            if ok:
                self.last_frame += 1
            return frame if ok else None

    def reconnect(self):
        with self.lock:
            self.cap.release()
            if isinstance(self.source, StreamSource) and self.source.is_youtube:
                self.source = resolve_stream(self.source.original_url, default_name=self.source.display_name)
            self._open()

    def close(self):
        with self.lock:
            if self.cap is not None:
                self.cap.release()


class CachedPlayback:
    """Only raw detections; ByteTrack and all behavior processing still run locally."""
    def __init__(self, cache_path: Path, video_path: Path | None = None):
        self.cache = DetectionCache.model_validate_json(cache_path.read_text())
        if video_path is not None and self.cache.video_sha256 != video_digest(video_path):
            raise ValueError('Cached detections do not match this video. Run precompute_demo.py for this exact clip.')
        self.index = 0

    def next(self):
        if self.index >= len(self.cache.frames):
            return None
        sample = self.cache.frames[self.index]
        self.index += 1
        return sample.frame, sample.timestamp, [Detection(*d.bbox, d.confidence, d.class_name) for d in sample.detections]
