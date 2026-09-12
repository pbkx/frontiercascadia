#!/usr/bin/env python3
"""Compare Fyolo's actual directional crossing counts with manual counts."""
import argparse
import json
from pathlib import Path
import sys
import time
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.models.schemas import Calibration
from backend.app.video.processor import VideoProcessor


class GroundTruth(BaseModel):
    upstream: int = Field(ge=0, strict=True)
    downstream: int = Field(default=0, ge=0, strict=True)
    calibration: Calibration = Field(default_factory=Calibration)


def validate(video: Path, ground_truth: Path, detections: Path | None = None) -> dict:
    truth = GroundTruth.model_validate_json(ground_truth.read_text())
    if detections is None:
        candidates = [video.with_name(video.stem + '_detections.json'), video.parent / 'detections.json']
        detections = next((p for p in candidates if p.exists()), None)
    processor = VideoProcessor(video, detections, truth.calibration.model_dump())
    if processor.error or processor.warning:
        processor.close()
        raise ValueError(processor.error or processor.warning)
    started = time.perf_counter()
    try:
        while processor.step():
            pass
        if processor.error:
            raise ValueError(processor.error)
        seconds = time.perf_counter() - started
        summary = processor.engine.snapshot()['summary']
        expected = truth.upstream + truth.downstream
        actual = summary['upstream'] + summary['downstream']
        return {
            'human_passage_count': expected, 'salmonsight_passage_count': actual,
            'absolute_count_error': abs(expected - actual),
            'percentage_count_error': round(abs(expected - actual) / expected * 100, 2) if expected else None,
            'directional_counts': {'human_upstream': truth.upstream, 'observed_upstream': summary['upstream'], 'human_downstream': truth.downstream, 'observed_downstream': summary['downstream']},
            'tracks_produced': summary['tracks_produced'], 'average_processing_fps': round(processor.index / max(.001, seconds), 2),
            'mode': processor.mode, 'samples_processed': processor.index,
            'note': 'Counts are directional gate-crossing events. Processing FPS is unpaced pipeline throughput, not camera FPS. No percentage is reported for zero ground truth.',
        }
    finally:
        processor.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--ground-truth', type=Path, required=True)
    parser.add_argument('--detections', type=Path)
    parser.add_argument('--output', type=Path, help='Optional JSON report path')
    args = parser.parse_args()
    try:
        result = validate(args.video, args.ground_truth, args.detections)
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Validation failed: {exc}\n')
    for label, key in [('Human passage count', 'human_passage_count'), ('Fyolo passage count', 'salmonsight_passage_count'), ('Absolute count error', 'absolute_count_error'), ('Percentage count error', 'percentage_count_error'), ('Tracks produced', 'tracks_produced'), ('Average processing FPS', 'average_processing_fps')]:
        value = result[key]
        print(f'{label}: {value if value is not None else "N/A (zero ground truth)"}')
    print(json.dumps(result['directional_counts'], indent=2))
    print(result['note'])
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
