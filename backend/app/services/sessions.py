import asyncio
import time
import uuid
from pathlib import Path
from ..config import settings
from ..models.schemas import Calibration
from ..video.processor import VideoProcessor
from ..video.sources import discover_demo

LABELS = {'LIVE_INFERENCE': 'LIVE INFERENCE', 'PRECOMPUTED_DEMO': 'PREPROCESSED DEMO', 'VISUALIZATION_DEMO': 'SIMULATED DATA'}


class Session:
    def __init__(self, source: str = 'demo'):
        self.id = uuid.uuid4().hex
        self.video, self.cache = discover_demo() if source == 'demo' else (None, None)
        if source == 'demo' and not self.video and settings.default_stream_url:
            self.video = settings.default_stream_url
        self.calibration = Calibration()
        self.calibration_required = False
        self.display_name = None
        self.processor = VideoProcessor(self.video, self.cache, self.calibration.model_dump())
        self.running = False
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.processing_fps = 0.
        self.last_access = time.monotonic()
        self.version = 0

    async def stop(self):
        self.running = False
        if self.task and not self.task.done():
            await self.task
        self.task = None

    async def reset(self):
        await self.stop()
        self.processor.close()
        self.processor = await asyncio.to_thread(VideoProcessor, self.video, self.cache, self.calibration.model_dump())
        self.processing_fps = 0.
        self.version += 1

    async def start(self):
        if self.running:
            return
        if self.calibration_required:
            raise ValueError('Choose the upstream direction and passage gate before starting custom footage.')
        if self.processor.completed or self.processor.error:
            await self.reset()
        if self.processor.error:
            return
        self.running = True
        self.task = asyncio.create_task(self.run())

    async def run(self):
        while self.running:
            started = time.perf_counter()
            try:
                advanced = await asyncio.to_thread(self.processor.step)
            except Exception:
                # Avoid exception text from SDKs / stream URLs reaching the browser.
                self.processor.error = 'Processing stopped. Check video compatibility and detector configuration, then retry.'
                advanced = False
            elapsed = time.perf_counter() - started
            self.processing_fps = 1 / max(elapsed, 1 / self.processor.sample_fps)
            self.version += 1
            if not advanced:
                self.running = False
                break
            await asyncio.sleep(max(0, 1 / self.processor.sample_fps - elapsed))

    def snapshot(self, lightweight: bool = True) -> dict:
        self.last_access = time.monotonic()
        p = self.processor
        with p.analytics_lock:
            analytics = p.engine.snapshot()
        if lightweight:
            # Preserve whole-journey shape using bounded, evenly sampled history.
            for track in analytics['tracks']:
                history = track['trajectory']
                if len(history) > 100:
                    indices = [round(i * (len(history) - 1) / 99) for i in range(100)]
                    track['trajectory'] = [history[i] for i in indices]
        if self.video is None:
            source_name = 'Illustrative salmon passage'
        elif isinstance(self.video, Path):
            source_name = self.display_name or self.video.name
        else:
            source_name = 'Configured stream'
        reader = p.reader
        state = {
            'id': self.id, 'mode': p.mode, 'label': LABELS[p.mode], 'source_name': source_name,
            'running': self.running, 'completed': p.completed, 'error': p.error or p.warning,
            'detector_state': 'MODEL UNAVAILABLE' if p.error else ('CACHED FISHIAL' if p.cache else ('ILLUSTRATIVE' if not self.video else 'LOCAL ' + settings.detector_backend.upper())),
            'video_url': f'/api/sessions/{self.id}/video' if self.video else None,
            'original_video_url': f'/api/sessions/{self.id}/original' if isinstance(self.video, Path) else None,
            'width': reader.width if reader else 1920, 'height': reader.height if reader else 1080,
            'duration': reader.total_frames / reader.fps if reader and reader.total_frames else None,
            'calibration_required': self.calibration_required, 'calibration': self.calibration.model_dump(),
        }
        return {'session': state, 'frame': p.frame, 'timestamp': p.timestamp, 'processing_fps': round(self.processing_fps, 1), **analytics, 'simulation_fish': p.simulation_fish}

    async def close(self):
        await self.stop()
        self.processor.close()


sessions: dict[str, Session] = {}
