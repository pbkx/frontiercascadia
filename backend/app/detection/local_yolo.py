from .fishial import FishialDetector


class LocalYoloDetector(FishialDetector):
    """Opt-in compatible local YOLO weights with a general `fish` detection class."""
    def __init__(self, model_path: str, threshold: float = .35, device: str = 'auto'):
        super().__init__(model_path, threshold, device)
        self.model_id = 'local_yolo/' + self.path.name
