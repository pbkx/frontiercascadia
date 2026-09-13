"""Temporary fixture detections test transport/algorithms, never model accuracy."""
import json
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace
import sys
import time
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.config import settings
from backend.app.detection.base import Detection, DetectorUnavailable
from backend.app.detection.fishial import FishialDetector, normalize_yolo_result
from backend.app.main import app
from backend.app.models.schemas import DetectionCache
from backend.app.video.sources import CachedPlayback, StreamSource, VideoReader, resolve_stream, video_digest
from backend.app.video.processor import VideoProcessor
from backend.app.video.simulation import synthetic_fish
from scripts.precompute_demo import precompute
from scripts.validate import validate


@pytest.fixture
def video(tmp_path):
    path = tmp_path / 'fixture.avi'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 10, (320, 180))
    assert writer.isOpened()
    for i in range(60):
        frame = np.full((180, 320, 3), 35 + i, np.uint8)
        cv2.putText(frame, 'TEST FIXTURE', (30, 80), cv2.FONT_HERSHEY_SIMPLEX, .5, (150, 180, 150), 1)
        writer.write(frame)
    writer.release()
    return path


class FixtureDetector:
    model_id = 'fixture/not-a-benchmark'
    model_sha256 = '0' * 64
    def __init__(self):
        self.index = 0

    def detect(self, frame):
        x = .14 + self.index * .013
        self.index += 1
        return [Detection(x - .04, .4, min(1., x + .04), .5, .94)]


@pytest.fixture
def cache(video):
    path = video.with_name('fixture_detections.json')
    precompute(video, path, 10, FixtureDetector())
    return path


def test_yolo_normalizes_only_valid_general_fish():
    import torch
    result = SimpleNamespace(names={0: 'Fish', 1: 'person'}, boxes=SimpleNamespace(
        xyxyn=torch.tensor([[.3, .3, .7, .7], [-.1, -.1, .06, .12], [.2, .2, .5, .5], [.2, .2, .5, .5], [float('nan'), .2, .5, .5]]),
        conf=torch.tensor([.94, .6, .94, .1, .9]), cls=torch.tensor([0, 0, 1, 0, 0]),
    ))
    detections = normalize_yolo_result(result)
    assert len(detections) == 2
    assert detections[0].bbox == pytest.approx([.3, .3, .7, .7])
    assert detections[1].bbox == pytest.approx([0, 0, .06, .12])
    assert all(d.class_name == 'fish' for d in detections)


def test_missing_model_does_not_download_or_substitute_coco(tmp_path, monkeypatch):
    import requests
    monkeypatch.setattr(requests.sessions.Session, 'request', Mock(side_effect=AssertionError('No downloads allowed')))
    with pytest.raises(DetectorUnavailable, match='Fishial model missing'):
        FishialDetector(str(tmp_path / 'missing.pt'))


def test_coco_checkpoint_is_rejected(tmp_path, monkeypatch):
    import ultralytics
    path = tmp_path / 'coco.pt'
    path.write_bytes(b'test')
    monkeypatch.setattr(ultralytics, 'YOLO', Mock(return_value=SimpleNamespace(task='detect', names={0: 'person', 1: 'car'})))
    with pytest.raises(DetectorUnavailable, match='not a fish detection model'):
        FishialDetector(str(path))


def test_inference_failure_is_not_an_empty_detection_frame(tmp_path, monkeypatch):
    import ultralytics
    path = tmp_path / 'fixture.pt'
    path.write_bytes(b'test')
    model = Mock(task='detect', names={0: 'Fish'})
    model.predict.side_effect = RuntimeError('Unsupported hardware')
    monkeypatch.setattr(ultralytics, 'YOLO', Mock(return_value=model))
    detector = FishialDetector(str(path), device='cpu')
    with pytest.raises(DetectorUnavailable, match='inference failed'):
        detector.detect(np.zeros((8, 8, 3), np.uint8))


def test_video_reader_seeks_and_repeats_exact_frame(video):
    reader = VideoReader(video)
    first = reader.read(0)
    assert np.array_equal(first, reader.read(0))
    assert not np.array_equal(first, reader.read(20))
    assert np.array_equal(first, reader.read(0))
    reader.close()


def test_direct_and_youtube_urls_resolve_without_exposing_page_url(monkeypatch):
    direct = resolve_stream('https://example.com/camera/live.m3u8')
    assert direct.resolved_url == direct.original_url
    assert direct.is_live and not direct.is_youtube

    class FakeYoutubeDL:
        def __init__(self, options):
            assert 'bestvideo' in options['format']
            assert 'height<=720' in options['format']
            assert options['format'].startswith('bestvideo[height<=720][ext=mp4][protocol=https]')
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def extract_info(self, url, download=False):
            assert not download and 'watch?v=' in url
            return {'url': 'https://media.example/live.m3u8', 'title': 'Camera', 'is_live': True, 'duration': 123}

    monkeypatch.setitem(sys.modules, 'yt_dlp', SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    youtube = resolve_stream('https://www.youtube.com/watch?v=fixture')
    assert youtube.resolved_url == 'https://media.example/live.m3u8'
    assert youtube.original_url != youtube.resolved_url
    assert youtube.is_youtube and youtube.is_live
    assert youtube.duration == 123


def test_display_reader_is_paced_and_inference_skips_stale_frames(video, monkeypatch):
    class SlowDetector(FixtureDetector):
        def detect(self, frame):
            time.sleep(.18)
            return super().detect(frame)

    monkeypatch.setattr('backend.app.video.processor.create_detector', SlowDetector)
    processor = VideoProcessor(video)
    processor.start_reader()
    deadline = time.monotonic() + 2
    while processor.latest_frame_id < 2 and time.monotonic() < deadline:
        time.sleep(.02)
    assert processor.detect_latest() is True
    first_processed = processor.processed_frame_id
    time.sleep(.24)
    assert processor.detect_latest() is True
    assert processor.processed_frame_id - first_processed >= 2
    assert 7 <= processor.display_fps <= 13
    assert processor.latest_frame_id > processor.processed_frame_id
    processor.close()


def test_recorded_playback_pause_and_seek_freeze_analytics(video, monkeypatch):
    monkeypatch.setattr('backend.app.video.processor.create_detector', FixtureDetector)
    processor = VideoProcessor(video)
    processor.start_reader()
    deadline = time.monotonic() + 2
    while processor.latest_frame_id < 3 and time.monotonic() < deadline:
        time.sleep(.02)
    assert processor.seekable
    assert processor.detect_latest() is True
    processor.engine.counts['upstream'] = 3
    processor.engine.counts['reversals'] = 2
    processor.engine.heatmaps.density[2, 3] = 4.0
    processor.set_playback_paused(True)
    time.sleep(.1)  # allow an already-started display read to settle
    frozen_frame = processor.latest_frame_id
    frozen_summary = processor.engine.snapshot()['summary']
    time.sleep(.2)
    assert processor.latest_frame_id == frozen_frame
    assert processor.detect_latest() is None
    assert processor.engine.snapshot()['summary'] == frozen_summary

    position = processor.seek(3.0)
    assert position == pytest.approx(3.0, abs=1 / processor.reader.fps)
    assert processor.playback_paused
    assert processor.engine.snapshot()['summary'] == frozen_summary
    assert processor.analysis_generation == 0

    processor.set_playback_paused(False)
    deadline = time.monotonic() + 2
    while processor.latest_frame_id <= round(3 * processor.reader.fps) and time.monotonic() < deadline:
        time.sleep(.02)
    assert processor.detect_latest() is True
    assert processor.analysis_generation == 1
    preserved = processor.engine.snapshot()['summary']
    assert preserved['upstream'] == 3
    assert preserved['reversals'] == 2
    assert processor.engine.heatmaps.density[2, 3] == 4.0
    assert processor.engine.archived
    assert all(track_id >= 1_000_000 for track_id in processor.engine.tracks)
    visible_tracks = processor.engine.snapshot()['tracks']
    assert all(track['display_id'] < 100 for track in visible_tracks)
    assert len({track['display_id'] for track in visible_tracks}) == len(visible_tracks)
    processor.close()


def test_recorded_event_replay_loops_until_closed(video, monkeypatch):
    monkeypatch.setattr('backend.app.video.processor.create_detector', FixtureDetector)
    processor = VideoProcessor(video)

    start, end = processor.replay_window(1., before=.2, after=.2)
    assert (start, end) == pytest.approx((.8, 1.2))
    assert processor.replaying and processor.analysis_paused

    deadline = time.monotonic() + 1.2
    saw_end = False
    saw_loop = False
    previous = processor.playback_position
    while time.monotonic() < deadline and not saw_loop:
        current = processor.playback_position
        saw_end = saw_end or current >= 1.1
        saw_loop = saw_loop or saw_end and current < previous
        previous = current
        time.sleep(.02)
    assert saw_loop
    assert processor.replaying and not processor.source_ended

    processor.set_playback_paused(True)
    time.sleep(.12)  # allow an already-started frame read to settle
    frozen = processor.playback_position
    time.sleep(.15)
    assert processor.playback_position == pytest.approx(frozen)
    processor.stop_replay()
    assert not processor.replaying and processor.playback_paused
    processor.close()


def test_live_reader_reconnects_after_a_failed_read(monkeypatch):
    frame = np.full((90, 160, 3), 50, np.uint8)

    class FlakyReader:
        fps = 10.
        total_frames = 0
        width = 160
        height = 90
        is_live = True
        def __init__(self, source):
            self.calls = 0
            self.reconnections = 0
        def read(self, number):
            return frame.copy()
        def read_next(self):
            self.calls += 1
            return None if self.calls == 1 else frame.copy()
        def reconnect(self, *, refresh=True):
            self.reconnections += 1
            assert not refresh
        def close(self):
            pass

    monkeypatch.setattr('backend.app.video.processor.VideoReader', FlakyReader)
    monkeypatch.setattr('backend.app.video.processor.create_detector', FixtureDetector)
    processor = VideoProcessor(StreamSource('https://example.com/live.m3u8', 'https://media.example/live.m3u8', 'Test live'))
    processor.start_reader()
    deadline = time.monotonic() + 2
    while processor.latest_frame_id < 1 and time.monotonic() < deadline:
        time.sleep(.02)
    assert processor.reader.reconnections == 1
    assert processor.reconnect_attempts == 1
    assert processor.jpeg.startswith(b'\xff\xd8')
    assert processor.stream_error is None
    processor.close()


def test_live_buffer_can_pause_seek_and_replay_without_pausing_detection(monkeypatch):
    frame = np.full((90, 160, 3), 30, np.uint8)

    class BufferedLiveReader:
        fps = 10.
        total_frames = 0
        duration = None
        width = 160
        height = 90
        is_live = True
        def __init__(self, source):
            pass
        def read(self, number):
            return frame.copy()
        def close(self):
            pass

    monkeypatch.setattr(settings, 'live_buffer_seconds', 6.)
    monkeypatch.setattr('backend.app.video.processor.VideoReader', BufferedLiveReader)
    monkeypatch.setattr('backend.app.video.processor.create_detector', FixtureDetector)
    processor = VideoProcessor(StreamSource('https://example.com/live.m3u8', 'https://media.example/live.m3u8', 'Test live'))
    for second in range(1, 11):
        current = np.full((90, 160, 3), 30 + second, np.uint8)
        processor._publish_frame(current, second * 10, float(second))
    start, end = processor.playback_bounds
    assert start == pytest.approx(4.)
    assert end == pytest.approx(10.)
    assert processor.seekable and processor.at_live_edge

    processor.set_playback_paused(True)
    processor.seek(6.)
    assert processor.playback_paused
    assert processor.playback_position == pytest.approx(6.)
    assert not processor.at_live_edge
    assert processor.detect_latest() is True
    processor._store_live_overlay(6., [{'id': 6, 'trajectory': [[.2, .5, 6.]]}])
    processor._store_live_overlay(9., [{'id': 9, 'trajectory': [[.8, .5, 9.]]}])
    assert processor.replay_tracks is None

    replay_start, replay_end = processor.replay_window(7.)
    assert replay_start == pytest.approx(4.)
    assert replay_end == pytest.approx(10.)
    assert not processor.playback_paused
    assert processor.detect_latest() is None  # The newest frame was already analyzed.
    assert processor.replay_tracks[0]['id'] == 6
    assert processor.timeline_bounds == pytest.approx((4., 10.))
    processor.seek(8.)
    assert processor.replaying
    assert processor.playback_position == pytest.approx(8.)
    processor.set_playback_paused(True)
    assert processor.replaying and processor.playback_paused
    processor.set_playback_paused(False)
    processor._live_playback_anchor = 4.
    processor._live_playback_started = time.monotonic() - 6.1
    assert processor.playback_position == pytest.approx(4.1, abs=.05)
    assert not processor.playback_paused
    assert processor.replaying and not processor.at_live_edge
    processor.stop_replay()
    assert not processor.replaying and processor.at_live_edge
    with pytest.raises(ValueError, match='outside the available'):
        processor.replay_window(2.)
    processor.close()


def test_live_reader_keeps_reconnecting_after_retry_budget(monkeypatch):
    frame = np.full((90, 160, 3), 80, np.uint8)

    class RecoveringReader:
        fps = 30.
        total_frames = 0
        duration = None
        width = 160
        height = 90
        is_live = True
        def __init__(self, source):
            self.calls = 0
            self.refreshes = []
        def read(self, number):
            return frame.copy()
        def read_next(self):
            self.calls += 1
            return frame.copy() if self.calls > 3 else None
        def reconnect(self, *, refresh=True):
            self.refreshes.append(refresh)
        def close(self):
            pass

    monkeypatch.setattr(settings, 'stream_reconnect_attempts', 2)
    monkeypatch.setattr('backend.app.video.processor.VideoReader', RecoveringReader)
    monkeypatch.setattr('backend.app.video.processor.create_detector', FixtureDetector)
    processor = VideoProcessor(StreamSource('https://example.com/live.m3u8', 'https://media.example/live.m3u8', 'Test live'))
    processor.start_reader()
    deadline = time.monotonic() + 5
    while processor.latest_frame_id < 1 and time.monotonic() < deadline:
        time.sleep(.02)
    assert processor.reader.calls > settings.stream_reconnect_attempts
    assert processor.reader.refreshes == [False, True, False]
    assert processor.jpeg.startswith(b'\xff\xd8')
    assert processor.stream_error is None
    assert processor.reconnecting is False
    processor.close()


def test_cache_has_raw_boxes_timestamps_and_video_fingerprint(video, cache):
    data = DetectionCache.model_validate_json(cache.read_text())
    assert data.video_sha256 == video_digest(video)
    assert data.model_id == 'fixture/not-a-benchmark'
    assert data.frames[18].timestamp == 1.8
    assert 'tracks' not in data.model_dump()
    playback = CachedPlayback(cache, video)
    for i in range(60):
        number, timestamp, detections = playback.next()
        assert number == i and timestamp == i / 10
        assert isinstance(detections[0], Detection)
    assert playback.next() is None


def test_cache_mismatch_and_non_monotonic_frames_are_rejected(video, cache, tmp_path):
    wrong = tmp_path / 'wrong.avi'
    wrong.write_bytes(b'not this video')
    with pytest.raises(ValueError, match='do not match'):
        CachedPlayback(cache, wrong)
    data = json.loads(cache.read_text())
    data['frames'][1]['timestamp'] = 0
    with pytest.raises(ValueError, match='increasing'):
        DetectionCache.model_validate(data)


def test_offline_cache_runs_bytetrack_and_behavior_without_detector(video, cache, monkeypatch):
    def forbidden():
        pytest.fail('Cached replay must never construct a detector')
    monkeypatch.setattr('backend.app.video.processor.create_detector', forbidden)
    processor = VideoProcessor(video, cache, {'upstream': [1, 0], 'gate': [[.65, .1], [.65, .9]]})
    while processor.step():
        pass
    result = processor.engine.snapshot()
    assert processor.mode == 'PRECOMPUTED_DEMO'
    assert result['summary']['upstream'] == 1
    assert result['summary']['successful'] == 0
    assert result['summary']['tracks_produced'] == 1
    assert len(result['tracks'][0]['trajectory']) == 60
    assert processor.jpeg[:2] == b'\xff\xd8'
    processor.close()


def test_failed_precompute_preserves_prior_complete_cache(video, cache):
    before = cache.read_bytes()
    class FailedDetector:
        def detect(self, frame):
            raise DetectorUnavailable('Test inference outage')
    with pytest.raises(DetectorUnavailable):
        precompute(video, cache, 10, FailedDetector())
    assert cache.read_bytes() == before


def test_validation_uses_actual_pipeline_counts(video, cache, tmp_path):
    truth = tmp_path / 'truth.json'
    truth.write_text(json.dumps({'upstream': 1, 'downstream': 0}))
    result = validate(video, truth, cache)
    assert result['absolute_count_error'] == 0
    assert result['tracks_produced'] == 1
    assert result['average_processing_fps'] > 0
    truth.write_text(json.dumps({'upstream': 0}))
    assert validate(video, truth, cache)['percentage_count_error'] is None


def test_visualization_has_unique_fish_and_real_local_analysis():
    assert len({f['id'] for f in synthetic_fish(20)}) == len(synthetic_fish(20))
    processor = VideoProcessor()
    for _ in range(430):
        assert processor.step()
    summary = processor.engine.snapshot()['summary']
    assert summary['upstream'] > 0 and summary['reversals'] > 0 and summary['long_dwell'] > 0
    assert processor.engine.snapshot()['heatmaps']['hotspot'] is not None
    assert processor.mode == 'VISUALIZATION_DEMO'


def test_api_health_session_websocket_controls_and_calibration(monkeypatch):
    monkeypatch.setattr(settings, 'fishial_model_path', 'models/missing-test.pt')
    with TestClient(app) as client:
        assert client.get('/api/health').json()['status'] == 'ok'
        initial = client.post('/api/sessions', json={'source': 'visualization'}).json()
        session_id = initial['session']['id']
        root = f'/api/sessions/{session_id}'
        assert initial['session']['label'] == 'SIMULATED DATA'
        assert initial['summary']['upstream'] == 0
        with client.websocket_connect(f'/ws/sessions/{session_id}') as ws:
            assert ws.receive_json()['session']['id'] == session_id
            assert client.post(root + '/start').json()['session']['running']
            for _ in range(5):
                result = ws.receive_json()
                if result['tracks']:
                    break
            assert len(result['tracks']) > 0
            analytics = client.get(root + '/analytics?range=5m')
            assert analytics.status_code == 200
            assert analytics.json()['summary']['fish_tracked'] > 0
            assert analytics.json()['range'] == '5m'
            assert client.get(root + '/analytics?range=day').status_code == 422
        assert not client.post(root + '/pause').json()['session']['running']
        invalid = client.post(root + '/calibration', json={'gate': [[0, 0], [0, 0]]})
        assert invalid.status_code == 422
        valid = client.post(root + '/calibration', json={'upstream': [0, -1], 'gate': [[.1, .5], [.9, .5]]})
        assert valid.status_code == 200
        assert valid.json()['summary']['upstream'] == 0
        assert client.get(root + '/events').status_code == 200
        assert client.get(root + '/tracks').status_code == 200
        assert client.delete(root).json()['deleted']
        assert client.get(root).status_code == 404


def test_upload_requires_calibration_and_missing_model_does_not_fake_tracks(video, monkeypatch):
    monkeypatch.setattr(settings, 'fishial_model_path', 'models/missing-test.pt')
    with TestClient(app) as client:
        session_id = client.post('/api/sessions', json={'source': 'visualization'}).json()['session']['id']
        root = f'/api/sessions/{session_id}'
        assert client.post(root + '/source', files={'file': ('bad.txt', b'test')}).status_code == 415
        response = client.post(root + '/source', files={'file': ('clip.avi', video.read_bytes(), 'video/x-msvideo')})
        assert response.status_code == 200
        state = response.json()['session']
        assert state['calibration_required']
        assert state['playback_paused']
        assert 'Fishial model missing' in state['error']
        assert response.json()['tracks'] == []
        assert client.post(root + '/start').status_code == 409
        assert client.post(root + '/calibration', json={}).status_code == 200
        result = client.post(root + '/start').json()
        assert not result['session']['running']
        assert result['session']['detector_state'] == 'MODEL UNAVAILABLE'
        assert result['simulation_fish'] == []
