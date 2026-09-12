from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / '.env'), extra='ignore', env_ignore_empty=True)
    detector_backend: str = 'fishial'
    fishial_model_path: str = 'models/fishial.pt'
    inference_device: str = 'auto'
    local_model_path: str = ''
    default_stream_url: str = ''
    default_demo_video_path: str = 'data/demo/salmon_demo.mp4'
    demo_detections_path: str = 'data/demo/detections.json'
    confidence_threshold: float = 0.35
    inference_sample_fps: float = 10.0
    reversal_threshold: float = 0.025
    dwell_threshold_seconds: float = 8.0
    track_history_length: int = 600
    backend_port: int = 8000


settings = Settings()
