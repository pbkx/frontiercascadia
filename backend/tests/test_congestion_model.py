from pathlib import Path
import socket
import numpy as np
import pytest
from backend.app.behavior import BehaviorEngine
from backend.app.config import ROOT
from backend.app.detection.fishial import FishialDetector


def test_congestion_requires_persistent_cluster_and_is_throttled():
    engine = BehaviorEngine()
    cluster = [{'id': i + 1, 'bbox': [.3 + i*.01, .4, .4 + i*.01, .45], 'confidence': .94} for i in range(4)]
    for i in range(10):
        engine.update(cluster, i / 10)
    assert not any(e['type'] == 'CONGESTION' for e in engine.snapshot()['events'])
    for i in range(10, 80):
        engine.update(cluster, i / 10)
    assert len([e for e in engine.snapshot()['events'] if e['type'] == 'CONGESTION']) == 1


@pytest.mark.skipif(not (ROOT / 'models/fishial.pt').is_file(), reason='Optional actual-model smoke test; run download_model.py first')
def test_installed_fishial_checkpoint_runs_with_network_disabled(monkeypatch):
    import torch
    import ultralytics
    def forbidden(*args, **kwargs):
        raise AssertionError('Runtime attempted a network connection')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    detector = FishialDetector('models/fishial.pt', device='cpu')
    assert {str(v).lower() for v in detector.model.names.values()} == {'fish'}
    assert detector.detect(np.zeros((360, 640, 3), np.uint8)) == []
