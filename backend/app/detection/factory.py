from ..config import settings
from .base import DetectorUnavailable
from .fishial import FishialDetector
from functools import lru_cache
from pathlib import Path
from ..config import ROOT


@lru_cache(maxsize=2)
def _load(backend, path, modified, threshold, device):
    if backend == 'fishial':
        return FishialDetector(path, threshold, device)
    if backend == 'local_yolo':
        from .local_yolo import LocalYoloDetector
        return LocalYoloDetector(path, threshold, device)
    raise DetectorUnavailable('Unknown detector backend. Choose fishial or local_yolo.')


def create_detector():
    model_path = settings.fishial_model_path if settings.detector_backend == 'fishial' else settings.local_model_path
    path = Path(model_path)
    path = path if path.is_absolute() else ROOT / path
    modified = path.stat().st_mtime_ns if path.is_file() else 0
    return _load(settings.detector_backend, str(path), modified, settings.confidence_threshold, settings.inference_device)
