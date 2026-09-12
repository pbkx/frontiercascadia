from dataclasses import dataclass
from typing import Protocol
import numpy as np


@dataclass(frozen=True)
class Detection:
    """Detector-neutral bounding box in normalized image coordinates."""
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    class_name: str = 'fish'

    @property
    def bbox(self) -> list[float]:
        return [self.x1, self.y1, self.x2, self.y2]

    def to_dict(self) -> dict:
        return {'bbox': self.bbox, 'confidence': self.confidence, 'class_name': self.class_name}


class Detector(Protocol):
    def detect(self, frame: np.ndarray) -> list[Detection]: ...


class DetectorUnavailable(RuntimeError):
    """An actionable local model setup or inference failure."""
