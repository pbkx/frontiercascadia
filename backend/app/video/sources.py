from pathlib import Path
import hashlib
import cv2
from ..config import ROOT, settings
from ..detection.base import Detection
from ..models.schemas import DetectionCache


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
    candidates = [resolve_path(settings.default_demo_video_path), ROOT / 'data/demo/issaquah.mp4', ROOT / 'data/demo/salmon_demo.mp4']
    for video in candidates:
        if video.is_file():
            caches = [video.with_name(video.stem + '_detections.json'), resolve_path(settings.demo_detections_path)]
            return video, next((p for p in caches if p.is_file()), None)
    return None, None


class VideoReader:
    def __init__(self, source: Path | str):
        self.source = source
        if isinstance(source, str) and source.startswith(('http://', 'https://', 'rtsp://')):
            self.cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10000])
        else:
            self.cap = cv2.VideoCapture(str(source))
        if not self.cap.isOpened():
            self.cap.release()
            raise ValueError('Cannot decode this video. Use an MP4 with H.264 video or another OpenCV-compatible codec.')
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.
        if not 0 < self.fps < 1000:
            self.fps = 30.
        self.total_frames = max(0, int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)))
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.last_frame = -1

    def read(self, frame_number: int):
        if frame_number <= self.last_frame or frame_number - self.last_frame > 90:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        else:
            for _ in range(frame_number - self.last_frame - 1):
                if not self.cap.grab():
                    return None
        ok, frame = self.cap.read()
        self.last_frame = frame_number
        return frame if ok else None

    def close(self):
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
