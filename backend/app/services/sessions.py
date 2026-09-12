from __future__ import annotations

import asyncio
from pathlib import Path
import time
import uuid

from ..config import settings
from ..models.schemas import Calibration
from ..video.processor import VideoProcessor
from ..video.sources import StreamSource, resolve_stream


class Session:
    def __init__(self, source: str = 'demo'):
        self.id = uuid.uuid4().hex
        self.calibration = Calibration()
        self.calibration_required = False
        self.display_name = None
        self.source_type = 'simulated'
        self.cache = None
        if source == 'demo':
            self.video = resolve_stream(settings.default_stream_url, default_name='Issaquah SalmonCam')
            self.display_name = 'Issaquah SalmonCam'
            self.source_type = 'live'
        elif source == 'visualization':
            self.video = None
            self.display_name = 'Developer simulation'
        else:
            raise ValueError('Unknown source type.')
        self.processor = VideoProcessor(self.video, self.cache, self.calibration.model_dump())
        self.running = False
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.processing_fps = 0.
        self.last_access = time.monotonic()
        self.version = 0

    async def start_display(self):
        await asyncio.to_thread(self.processor.start_reader)

    async def stop(self):
        self.running = False
        if self.task and not self.task.done():
            await self.task
        self.task = None

    async def reset(self):
        await self.stop()
        self.processor.close()
        if isinstance(self.video, StreamSource) and self.video.is_youtube:
            self.video = await asyncio.to_thread(resolve_stream, self.video.original_url, default_name=self.display_name)
        self.processor = await asyncio.to_thread(VideoProcessor, self.video, self.cache, self.calibration.model_dump())
        await self.start_display()
        self.processing_fps = 0.
        self.version += 1

    async def replace_source(self, video, *, display_name: str, source_type: str, calibration_required: bool):
        await self.stop()
        processor = await asyncio.to_thread(VideoProcessor, video, None, self.calibration.model_dump())
        old = self.processor
        self.video, self.cache = video, None
        self.display_name = display_name
        self.source_type = source_type
        self.calibration_required = calibration_required
        self.processor = processor
        self.processing_fps = 0.
        self.version += 1
        old.close()
        await self.start_display()

    async def start(self):
        self.processor.start_reader()
        if self.running:
            return
        if self.calibration_required:
            raise ValueError('Choose the upstream direction and counting line before starting custom footage.')
        if self.processor.completed or self.processor.stream_error:
            await self.reset()
        if self.processor.detector_error or self.processor.stream_error:
            return
        self.running = True
        self.task = asyncio.create_task(self.run())

    async def run(self):
        next_detection = 0.
        while self.running:
            now = time.monotonic()
            if now < next_detection:
                await asyncio.sleep(min(.02, next_detection - now))
                continue
            started = time.perf_counter()
            try:
                if self.processor.mode == 'LIVE_INFERENCE' and not self.processor.cache:
                    advanced = await asyncio.to_thread(self.processor.detect_latest)
                else:
                    advanced = await asyncio.to_thread(self.processor.step)
            except Exception:
                self.processor.detector_error = 'Processing stopped. Check video compatibility and detector configuration, then retry.'
                advanced = False
            if advanced is None:
                await asyncio.sleep(.01)
                continue
            elapsed = time.perf_counter() - started
            if advanced:
                self.processing_fps = self.processor.analysis_fps
                next_detection = time.monotonic() + max(0., 1 / self.processor.sample_fps - elapsed)
                self.version += 1
            else:
                self.running = False
                break

    def snapshot(self, lightweight: bool = True) -> dict:
        self.last_access = time.monotonic()
        p = self.processor
        with p.analytics_lock:
            analytics = p.engine.snapshot()
        if lightweight:
            for track in analytics['tracks']:
                history = track['trajectory']
                if len(history) > 100:
                    indices = [round(i * (len(history) - 1) / 99) for i in range(100)]
                    track['trajectory'] = [history[i] for i in indices]
        if self.video is None:
            source_name = self.display_name or 'Developer simulation'
            label = 'SIMULATED DATA'
        elif self.source_type == 'upload':
            source_name = self.display_name or Path(self.video).name
            label = 'UPLOADED VIDEO'
        elif p.cache:
            source_name = self.display_name or 'Preprocessed demo'
            label = 'PREPROCESSED DEMO'
        else:
            source_name = self.display_name or (self.video.display_name if isinstance(self.video, StreamSource) else 'Video stream')
            label = 'LIVE' if self.source_type == 'live' else 'VIDEO STREAM'
        reader = p.reader
        passage_calibrated = self.calibration.entry_zone is not None and self.calibration.exit_zone is not None
        state = {
            'id': self.id, 'mode': p.mode, 'label': label, 'source_name': source_name,
            'running': self.running, 'completed': p.completed, 'error': p.error or p.warning,
            'detector_state': 'MODEL UNAVAILABLE' if p.detector_error else ('CACHED FISHIAL' if p.cache else ('ILLUSTRATIVE' if not self.video else 'LOCAL ' + settings.detector_backend.upper())),
            'video_url': f'/api/sessions/{self.id}/video' if self.video else None,
            'original_video_url': f'/api/sessions/{self.id}/original' if isinstance(self.video, Path) else None,
            'width': reader.width if reader else 1920, 'height': reader.height if reader else 1080,
            'duration': reader.total_frames / reader.fps if reader and reader.total_frames and not reader.is_live else None,
            'calibration_required': self.calibration_required, 'calibration': self.calibration.model_dump(),
            'source_type': self.source_type, 'passage_calibrated': passage_calibrated,
            'reconnecting': p.reconnecting, 'reconnect_attempts': p.reconnect_attempts,
            'display_fps': round(p.display_fps, 1),
        }
        return {'session': state, 'frame': p.frame, 'timestamp': p.timestamp, 'processing_fps': round(self.processing_fps, 1), **analytics, 'simulation_fish': p.simulation_fish}

    async def close(self):
        await self.stop()
        self.processor.close()


sessions: dict[str, Session] = {}
