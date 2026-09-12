#!/usr/bin/env python3
"""Cache real, raw LOCAL fish detections for a fully offline SalmonSight stage demo."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.config import settings
from backend.app.detection.factory import create_detector
from backend.app.detection.base import DetectorUnavailable
from backend.app.models.schemas import DetectionCache
from backend.app.video.sources import VideoReader, video_digest


def precompute(video: Path, output: Path, sample_fps: float, detector=None) -> dict:
    if video.resolve() == output.resolve():
        raise ValueError('Output must be a JSON file separate from the video.')
    if not video.is_file():
        raise ValueError(f'Video not found: {video}')
    if not 0 < sample_fps <= 60:
        raise ValueError('Sample FPS must be greater than zero and at most 60.')
    detector = detector or create_detector()
    reader = VideoReader(video)
    sample_fps = min(sample_fps, reader.fps)
    frames = []
    started = time.perf_counter()
    try:
        index = 0
        while True:
            number = round(index * reader.fps / sample_fps)
            if reader.total_frames and number >= reader.total_frames:
                break
            frame = reader.read(number)
            if frame is None:
                if reader.total_frames and number < reader.total_frames - max(1, reader.fps / sample_fps):
                    raise ValueError('Video decoding failed before the expected end. Cache was not published.')
                break
            # Any inference failure aborts; missing frames are never silently cached as no fish.
            detections = detector.detect(frame)
            frames.append({'frame': number, 'timestamp': number / reader.fps, 'detections': [d.to_dict() for d in detections]})
            index += 1
            if index % 25 == 0:
                print(f'Cached {index} samples · video {number / reader.fps:.1f}s · {index / (time.perf_counter() - started):.1f} inference FPS', flush=True)
        payload = {
            'schema_version': 1, 'provenance': 'fishial_local' if settings.detector_backend == 'fishial' else 'local_yolo',
            'model_id': detector.model_id, 'model_sha256': detector.model_sha256,
            'confidence_threshold': settings.confidence_threshold,
            'video': video.name, 'video_sha256': video_digest(video), 'fps': reader.fps,
            'sample_fps': sample_fps, 'width': reader.width, 'height': reader.height,
            'total_frames': reader.total_frames or (frames[-1]['frame'] + 1 if frames else 0), 'frames': frames,
        }
        validated = DetectionCache.model_validate(payload)
        output.parent.mkdir(parents=True, exist_ok=True)
        # Publish atomically, preserving a previous complete cache if preprocessing fails.
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile('w', dir=output.parent, suffix='.tmp', delete=False) as handle:
                temp_path = Path(handle.name)
                handle.write(validated.model_dump_json())
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.replace(output)
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)
        return {'samples': len(frames), 'detections': sum(len(f['detections']) for f in frames), 'processing_fps': len(frames) / max(.001, time.perf_counter() - started), 'output': str(output)}
    finally:
        reader.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--sample-fps', '--fps', type=float, default=settings.inference_sample_fps)
    args = parser.parse_args()
    try:
        report = precompute(args.video, args.output, args.sample_fps)
    except (ValueError, OSError, DetectorUnavailable) as exc:
        parser.exit(1, f'Precomputation failed: {exc}\nNo synthetic detections were substituted.\n')
    print(json.dumps(report, indent=2))
    print('Ready for offline playback. Keep this JSON beside its unchanged video.')


if __name__ == '__main__':
    main()
