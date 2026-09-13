import pytest

from backend.app.analytics import build_analytics


def track(track_id, first, last, direction, speed, distance, reversals=0, crossings=()):
    return {
        'id': track_id, 'first_seen': first, 'last_seen': last, 'time_observed': last - first,
        'direction': direction, 'velocity': speed, 'distance_traveled': distance,
        'reversals': reversals, 'gate_crossings': [{'direction': value, 'timestamp': last} for value in crossings],
    }


@pytest.fixture
def analytics_snapshot():
    tracks = [
        track(1, 10, 18, 'upstream', .20, .8, crossings=('upstream',)),
        track(2, 50, 56, 'upstream', .30, .9),
        track(3, 100, 116, 'downstream', .10, 1.2, 2, ('downstream',)),
        track(4, 550, 590, 'uncertain', .05, .5, 1),
    ]
    events = [
        {'id': 1, 'type': 'UPSTREAM_CROSSING', 'timestamp': 17, 'track_id': 1},
        {'id': 2, 'type': 'DOWNSTREAM_CROSSING', 'timestamp': 114, 'track_id': 3},
        {'id': 3, 'type': 'REVERSAL', 'timestamp': 108, 'track_id': 3},
        {'id': 4, 'type': 'LONG_DWELL', 'timestamp': 112, 'track_id': 3},
        {'id': 5, 'type': 'REVERSAL', 'timestamp': 570, 'track_id': 4, 'media_timestamp': 42},
    ]
    return {
        'session': {'id': 'test', 'source_type': 'upload', 'source_name': 'fixture.mp4'},
        'timestamp': 600., 'tracks': tracks, 'events': events,
    }


def test_analytics_uses_unique_tracks_and_real_events(analytics_snapshot):
    result = build_analytics(analytics_snapshot, 'all')
    assert result['summary'] == {
        'fish_tracked': 4, 'upstream_percent': 50., 'downstream_percent': 25.,
        'reversal_rate': 50., 'median_observed_time': 12., 'median_relative_speed': .15,
    }
    assert sum(item['fish_observed'] for item in result['activity']) == 4
    assert sum(item['upstream_crossings'] for item in result['activity']) == 1
    assert sum(item['reversals'] for item in result['behavior_events']) == 2
    assert sum(item['count'] for item in result['observed_time_distribution']) == 4
    assert sum(item['count'] for item in result['speed_distribution']) == 4
    assert result['normal_vs_reversal']['normal']['count'] == 2
    assert result['normal_vs_reversal']['reversal']['count'] == 2
    assert result['normal_vs_reversal']['normal']['upstream_crossing_rate'] == 50.
    assert len(result['scatter']) == 4
    assert [event['id'] for event in result['events']] == [5, 4, 3, 2, 1]
    assert result['events'][0]['media_timestamp'] == 42
    assert all('Fish #' not in finding or 'reversal behavior' in finding for finding in result['findings'])


def test_analytics_range_filters_every_section(analytics_snapshot):
    result = build_analytics(analytics_snapshot, '5m')
    assert result['observation']['start'] == 300.
    assert result['summary']['fish_tracked'] == 1
    assert result['direction'][2] == {'name': 'uncertain', 'count': 1, 'percent': 100.}
    assert sum(item['fish_observed'] for item in result['activity']) == 1
    assert sum(item['reversals'] for item in result['behavior_events']) == 1
    assert [item['id'] for item in result['tracks']] == [4]
    assert [event['id'] for event in result['events']] == [5]


def test_analytics_empty_states_are_finite_and_invalid_ranges_fail(analytics_snapshot):
    analytics_snapshot['tracks'] = []
    analytics_snapshot['events'] = []
    result = build_analytics(analytics_snapshot, 'all')
    assert result['summary']['fish_tracked'] == 0
    assert result['summary']['median_relative_speed'] is None
    assert result['findings'] == []
    assert result['scatter'] == []
    assert result['speed_distribution'] == []
    with pytest.raises(ValueError, match='Range must be'):
        build_analytics(analytics_snapshot, 'day')


def test_analytics_exposes_compact_display_id_without_replacing_internal_id(analytics_snapshot):
    analytics_snapshot['tracks'][0]['id'] = 1_000_794
    analytics_snapshot['tracks'][0]['display_id'] = 5
    result = build_analytics(analytics_snapshot, 'all')
    row = next(item for item in result['tracks'] if item['id'] == 1_000_794)
    point = next(item for item in result['scatter'] if item['id'] == 1_000_794)
    assert row['display_id'] == 5
    assert point['display_id'] == 5
