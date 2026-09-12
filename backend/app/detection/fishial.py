"""Local pretrained Fishial YOLO detection; never downloads weights at runtime."""
import hashlib
import math
import os
from pathlib import Path
from threading import RLock
import numpy as np
from ..config import ROOT
from .base import Detection, DetectorUnavailable


def normalize_yolo_result(result, threshold: float = .35) -> list[Detection]:
    """Ultralytics already reverses letterboxing in xyxyn; keep normalized fish boxes."""
    if result.boxes is None:
        return []
    boxes = result.boxes.xyxyn.cpu().numpy()
    scores = result.boxes.conf.cpu().numpy()
    classes = result.boxes.cls.cpu().numpy()
    detections = []
    for bbox, confidence, class_id in zip(boxes, scores, classes):
        if str(result.names.get(int(class_id), '')).lower() != 'fish':
            continue
        if not all(math.isfinite(float(v)) for v in (*bbox, confidence)) or not threshold <= confidence <= 1:
            continue
        clipped = np.clip(bbox, 0, 1).tolist()
        if clipped[2] > clipped[0] and clipped[3] > clipped[1]:
            detections.append(Detection(*clipped, float(confidence), 'fish'))
    return detections


class FishialDetector:
    def __init__(self, model_path: str = 'models/fishial.pt', threshold: float = .35, device: str = 'auto'):
        path = Path(model_path)
        self.path = path if path.is_absolute() else ROOT / path
        if not model_path or not self.path.is_file():
            raise DetectorUnavailable('Fishial model missing. Run .venv/bin/python scripts/download_model.py, or set FISHIAL_MODEL_PATH to a pretrained fish YOLO checkpoint.')
        os.environ['YOLO_OFFLINE'] = 'true'
        os.environ['YOLO_AUTOINSTALL'] = 'false'
        os.environ.setdefault('YOLO_CONFIG_DIR', str(ROOT / '.cache/ultralytics'))
        Path(os.environ['YOLO_CONFIG_DIR']).mkdir(parents=True, exist_ok=True)
        try:
            import torch
            from ultralytics import YOLO, settings as yolo_settings
            yolo_settings.update({'sync': False})
            self.device = ('cuda:0' if torch.cuda.is_available() else ('mps' if torch.backends.mps.is_available() else 'cpu')) if device == 'auto' else device
            self.requested_device = device
            self.model = YOLO(str(self.path), task='detect')
            if self.model.task != 'detect' or not any(str(name).lower() == 'fish' for name in self.model.names.values()):
                raise DetectorUnavailable('This checkpoint is not a fish detection model. Install the Fishial detector; generic COCO and species classifiers are not supported.')
            self.model.to(self.device)
        except DetectorUnavailable:
            raise
        except Exception:
            raise DetectorUnavailable('Could not load local Fishial weights. Run scripts/download_model.py and scripts/setup.sh; use INFERENCE_DEVICE=cpu if your accelerator is unsupported.') from None
        self.threshold = threshold
        self.lock = RLock()
        self.model_id = 'fishial/' + self.path.name
        self.model_sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def detect(self, frame: np.ndarray) -> list[Detection]:
        with self.lock:
            try:
                result = self.model.predict(source=frame, conf=self.threshold, iou=.45, imgsz=640, device=self.device, verbose=False, save=False)[0]
            except Exception:
                if self.requested_device != 'auto' or self.device == 'cpu':
                    raise DetectorUnavailable('Local Fishial inference failed. Check the video/model and try INFERENCE_DEVICE=cpu.') from None
                self.device = 'cpu'
                self.model.to('cpu')
                try:
                    result = self.model.predict(source=frame, conf=self.threshold, iou=.45, imgsz=640, device='cpu', verbose=False, save=False)[0]
                except Exception:
                    raise DetectorUnavailable('Local Fishial inference failed on CPU. Check the checkpoint and video format.') from None
            return normalize_yolo_result(result, self.threshold)
