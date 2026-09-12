import math

import numpy as np
import pytest

from backend.app.behavior import BehaviorEngine
from backend.app.behavior.heatmap import Heatmaps
from backend.app.detection.base import Detection
from backend.app.tracking import Tracker


def fish(x, y=0.51, track_id=1, confidence=0.93):
    return {'id': track_id, 'bbox': [x - 0.04, y - 0.02, x + 0.04, y + 0.02], 'confidence': confidence}


def follow(engine, positions, y=0.51, start=0.0, fps=10, confidence=0.93):
    snapshot = None
    for index, x in enumerate(positions):
        snapshot = engine.update([fish(float(x), y, confidence=confidence)], start + index / fps)
    return snapshot


def test_bytetrack_preserves_ids_through_motion_and_short_missing_observation():
    tracker = Tracker(sample_fps=10)
    observed_ids = []
    for frame in range(25):
        x = 0.15 + frame * 0.006
        detections = [] if frame == 12 else [Detection(x, 0.4, x + 0.12, 0.47, 0.93)]
        tracks = tracker.update(detections, frame / 10)
        if tracks:
            observed_ids.append(tracks[0].id)
            assert 0 <= tracks[0].bbox[0] < tracks[0].bbox[2] <= 1
    assert len(observed_ids) >= 20
    assert len(set(observed_ids)) == 1


def test_bytetrack_can_start_a_track_at_the_configured_low_confidence_threshold():
    tracker = Tracker(detection_threshold=0.20)
    tracks = tracker.update([Detection(0.2, 0.4, 0.5, 0.55, 0.21)], 0)
    assert len(tracks) == 1
    assert tracks[0].confidence == pytest.approx(0.21)


def test_bytetrack_keeps_independent_fish_and_rejects_invalid_boxes():
    tracker = Tracker()
    for frame in range(12):
        tracks = tracker.update([
            Detection(0.1 + frame * 0.004, 0.2, 0.2 + frame * 0.004, 0.26, 0.9),
            Detection(0.7 - frame * 0.004, 0.7, 0.8 - frame * 0.004, 0.76, 0.9),
            Detection(math.nan, 0.4, 0.5, 0.5, 0.9),
            Detection(0.7, 0.4, 0.6, 0.5, 0.9),
            Detection(0.3, 0.3, 0.4, 0.4, 0.9, 'person'),
        ], frame / 10)
        assert len(tracks) == 2
        ids = {track.id for track in tracks}
        if frame == 0:
            original_ids = ids
        assert ids == original_ids


@pytest.mark.parametrize('upstream,start,end,expected', [
    ([1, 0], 0.2, 0.8, 'upstream'),
    ([1, 0], 0.8, 0.2, 'downstream'),
    ([-1, 0], 0.8, 0.2, 'upstream'),
])
def test_direction_uses_calibrated_smoothed_motion(upstream, start, end, expected):
    engine = BehaviorEngine({'upstream': upstream})
    snapshot = follow(engine, np.linspace(start, end, 70))
    assert snapshot['tracks'][0]['direction'] == expected
    assert snapshot['summary'][expected] == 1


def test_gate_counts_once_and_ignores_hovering_jitter():
    engine = BehaviorEngine()
    positions = list(np.linspace(0.3, 0.669, 40)) + [0.647, 0.656, 0.645, 0.654] * 20
    snapshot = follow(engine, positions)
    assert snapshot['summary']['upstream'] == 1
    assert snapshot['summary']['downstream'] == 0
    assert snapshot['summary']['successful'] == 0
    assert len(snapshot['tracks'][0]['gate_crossings']) == 1


def test_line_extension_is_not_a_gate_crossing():
    snapshot = follow(BehaviorEngine(), np.linspace(0.3, 0.8, 60), y=0.95)
    assert snapshot['summary']['upstream'] == 0
    assert snapshot['summary']['successful'] == 0


def test_clearance_and_return_permit_genuine_new_crossings():
    positions = np.concatenate([np.linspace(0.2, 0.85, 65), np.linspace(0.85, 0.3, 55), np.linspace(0.3, 0.85, 55)])
    snapshot = follow(BehaviorEngine(), positions)
    assert snapshot['summary']['upstream'] == 2
    assert snapshot['summary']['downstream'] == 1
    assert snapshot['summary']['successful'] == 0
    assert snapshot['tracks'][0]['attempts'] == 2
    assert 'MULTIPLE_ATTEMPTS' in snapshot['tracks'][0]['flags']


def test_sustained_reversal_is_located_at_the_turn():
    positions = np.concatenate([np.linspace(0.2, 0.58, 40), np.linspace(0.58, 0.25, 40)])
    snapshot = follow(BehaviorEngine(), positions)
    track = snapshot['tracks'][0]
    assert track['reversals'] == 1
    assert track['status'] == 'REVERSED'
    assert track['reversal_locations'][0][0] == pytest.approx(0.58, abs=0.015)
    assert snapshot['heatmaps']['hotspot'] is None  # One turn is not a concentration.
    assert any(event['type'] == 'REVERSAL' for event in snapshot['events'])


def test_low_confidence_turn_and_stationary_jitter_do_not_flag_reversal():
    positions = np.concatenate([np.linspace(0.2, 0.58, 40), np.linspace(0.58, 0.25, 40)])
    snapshot = follow(BehaviorEngine(), positions, confidence=0.4)
    assert snapshot['summary']['reversals'] == 0
    snapshot = follow(BehaviorEngine(), [0.5 + 0.002 * math.sin(index) for index in range(120)])
    assert snapshot['summary']['reversals'] == 0
    assert snapshot['tracks'][0]['direction'] == 'uncertain'


def test_lateral_bend_is_not_a_reversal():
    engine = BehaviorEngine()
    for frame in range(40):
        snapshot = engine.update([fish(0.2 + frame * 0.006)], frame / 10)
    for frame in range(1, 41):
        snapshot = engine.update([fish(0.434, 0.51 + frame * 0.005)], (39 + frame) / 10)
    assert snapshot['summary']['reversals'] == 0


def test_approach_retreat_and_reapproach_create_two_attempts_without_pass():
    positions = np.concatenate([np.linspace(0.2, 0.57, 40), np.linspace(0.57, 0.3, 35), np.linspace(0.3, 0.57, 35)])
    snapshot = follow(BehaviorEngine(), positions)
    assert snapshot['summary']['attempts'] == 2
    assert snapshot['summary']['successful'] == 0
    assert snapshot['summary']['upstream'] == 0


def test_trajectory_history_bounded_without_losing_total_observed_time():
    engine = BehaviorEngine(history_length=12)
    snapshot = follow(engine, np.linspace(0.2, 0.6, 80))
    track = snapshot['tracks'][0]
    assert len(track['trajectory']) == 12
    assert track['trajectory'][-1][2] == pytest.approx(7.9)
    assert track['time_observed'] == pytest.approx(7.9)
    assert track['distance_traveled'] == pytest.approx(0.4)


@pytest.mark.parametrize('fps', [5, 10, 20])
def test_dwell_uses_seconds_and_generates_measured_heatmap(fps):
    engine = BehaviorEngine(sample_fps=fps, dwell_threshold_seconds=3)
    snapshot = follow(engine, [0.51] * (fps * 5 + 1), fps=fps)
    track = snapshot['tracks'][0]
    assert track['dwell_time'] == pytest.approx(5.0)
    assert engine.heatmaps.density.sum() == pytest.approx(5.0)
    assert snapshot['summary']['long_dwell'] == 1
    assert 'LONG_DWELL' in track['flags']
    assert snapshot['heatmaps']['hotspot']['dwell_seconds'] == 5.0
    assert snapshot['heatmaps']['hotspot']['baseline_ratio'] is None
    assert np.asarray(snapshot['heatmaps']['density']).shape == (12, 20)
    assert max(map(max, snapshot['heatmaps']['friction'])) == 1.0


def test_baseline_requires_three_measured_normal_successes():
    engine = BehaviorEngine({'entry_zone': [.1, .2, .3, .8], 'exit_zone': [.7, .2, .9, .8]})
    for frame, x in enumerate(np.linspace(0.2, 0.75, 70)):
        engine.update([fish(float(x), y, index + 1) for index, y in enumerate([0.31, 0.51])], frame / 10)
    assert engine.counts['successful'] == 2
    assert engine.baseline is None
    for frame, x in enumerate(np.linspace(0.2, 0.75, 70)):
        engine.update([fish(float(x), 0.71, 3)], 7 + frame / 10)
    assert engine.counts['successful'] == 3
    assert engine.baseline > 0


def test_hotspot_finds_supported_region_even_if_an_isolated_turn_has_more_weight():
    heatmaps = Heatmaps()
    heatmaps.reversal([0.2, 0.2])
    heatmaps.friction[8, 15] = 2.0
    heatmaps.dwell[8, 15] = 10.0
    hotspot = heatmaps.snapshot()['hotspot']
    assert hotspot is not None
    assert hotspot['dwell_seconds'] == 10.0
    assert hotspot['reversals'] == 0
    assert hotspot['baseline_ratio'] is None


def test_zone_calibration_requires_observed_entry_before_exit():
    calibration = {'entry_zone': [0.1, 0.2, 0.3, 0.8], 'exit_zone': [0.8, 0.2, 0.95, 0.8]}
    engine = BehaviorEngine(calibration)
    snapshot = follow(engine, np.linspace(0.2, 0.75, 60))
    assert snapshot['summary']['upstream'] == 1
    assert snapshot['summary']['successful'] == 0
    snapshot = follow(engine, np.linspace(0.76, 0.88, 20), start=6)
    assert snapshot['summary']['successful'] == 1
    snapshot = follow(BehaviorEngine(calibration), np.linspace(0.4, 0.88, 60))
    assert snapshot['summary']['successful'] == 0


def test_archive_and_events_are_bounded_but_lifetime_counts_survive():
    engine = BehaviorEngine(max_archived=3)
    for index in range(60):
        engine.update([fish(0.3, track_id=index + 1)], index * 3)
    snapshot = engine.finish(180)
    assert snapshot['summary']['active'] == 0
    assert snapshot['summary']['tracks_produced'] == 60
    assert len(snapshot['tracks']) == 3
    assert len(snapshot['events']) == 100
    assert all(not track['active'] and track['status'] == 'INCOMPLETE' for track in snapshot['tracks'])


def test_empty_engine_reports_unknown_rates_without_fabricated_statistics():
    snapshot = BehaviorEngine().snapshot()
    assert snapshot['summary']['success_rate'] is None
    assert snapshot['summary']['median_passage_seconds'] is None
    assert snapshot['heatmaps']['hotspot'] is None


def test_timestamps_cannot_run_backwards():
    engine = BehaviorEngine()
    engine.update([fish(0.3)], 2)
    with pytest.raises(ValueError, match='monotonic'):
        engine.update([fish(0.4)], 1)
    tracker = Tracker()
    tracker.update([], 2)
    with pytest.raises(ValueError, match='monotonic'):
        tracker.update([], 1)
