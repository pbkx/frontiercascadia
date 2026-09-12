"""Interpretable passage observations from bounded, persistent fish trajectories.

Distances are normalized image coordinates, not physical distances. A successful
upstream gate crossing is a passage proxy unless entry/exit zones are calibrated.
All counters describe observed tracks and can be affected by identity switches.
"""

from collections import OrderedDict, deque
import math
from statistics import median

from ..config import settings
from .attempts import AttemptState
from .crossings import CrossingState, PassageGate
from .dwell import residence_segments
from .heatmap import Heatmaps
from .reversals import ReversalState
from .trajectories import Track


def in_zone(point, zone):
    if zone is None:
        return True
    if len(zone) == 4 and isinstance(zone[0], (int, float)):
        x1, y1, x2, y2 = zone
        return min(x1, x2) <= point[0] <= max(x1, x2) and min(y1, y2) <= point[1] <= max(y1, y2)
    # Even-odd polygon containment, allowing arbitrary normalized calibration zones.
    inside = False
    previous = zone[-1]
    for current in zone:
        if (current[1] > point[1]) != (previous[1] > point[1]):
            x = (previous[0] - current[0]) * (point[1] - current[1]) / (previous[1] - current[1]) + current[0]
            if point[0] < x:
                inside = not inside
        previous = current
    return inside


class BehaviorEngine:
    def __init__(
        self, calibration: dict | None = None, sample_fps: float = 10, *,
        reversal_threshold: float | None = None, dwell_threshold_seconds: float | None = None,
        history_length: int | None = None, max_archived: int = 120,
    ):
        calibration = calibration or {}
        upstream = calibration.get('upstream', [1, 0])
        length = math.hypot(*upstream)
        if not math.isfinite(length) or length < 0.1:
            raise ValueError('Upstream must be a nonzero direction vector.')
        self.upstream = tuple(float(value) / length for value in upstream)
        self.gate = PassageGate(calibration.get('gate', [[0.62, 0.12], [0.62, 0.88]]), self.upstream)
        self.entry_zone, self.exit_zone = calibration.get('entry_zone'), calibration.get('exit_zone')
        self.sample_fps = max(1.0, float(sample_fps))
        self.reversal_threshold = max(0.005, reversal_threshold if reversal_threshold is not None else settings.reversal_threshold)
        self.dwell_threshold = max(0.5, dwell_threshold_seconds if dwell_threshold_seconds is not None else settings.dwell_threshold_seconds)
        self.history_length = max(2, history_length if history_length is not None else settings.track_history_length)
        self.max_archived = max(0, max_archived)
        self.tracks: dict[int, Track] = {}
        self.archived: OrderedDict[int, Track] = OrderedDict()
        self.crossing_states: dict[int, CrossingState] = {}
        self.reversal_states: dict[int, ReversalState] = {}
        self.attempt_states: dict[int, AttemptState] = {}
        self.heatmaps = Heatmaps()
        self.events = deque(maxlen=100)
        self._event_id = 0
        self.started_at: float | None = None
        self.timestamp = 0.0
        self.counts = {'upstream': 0, 'downstream': 0, 'successful': 0, 'attempts': 0, 'reversals': 0, 'long_dwell': 0, 'tracks_produced': 0}
        self.completed_count = 0
        # Rolling measured baseline: no ratio is emitted before three successes.
        self.successful_dwell = deque(maxlen=300)
        self.passage_times = deque(maxlen=300)
        self.congestion_since: float | None = None
        self.last_congestion = -math.inf

    def _event(self, kind, track, message, position=None):
        self._event_id += 1
        self.events.append({
            'id': self._event_id, 'type': kind, 'track_id': track.id, 'timestamp': self.timestamp,
            'position': list(position if position is not None else track.point), 'message': message,
        })

    @property
    def baseline(self):
        return median(self.successful_dwell) if len(self.successful_dwell) >= 3 else None

    @property
    def long_dwell_limit(self):
        return min(self.dwell_threshold, max(2.0, self.baseline * 2)) if self.baseline is not None else self.dwell_threshold

    def _new_track(self, track_id, bbox, confidence):
        track = Track(track_id, list(bbox), float(confidence), self.timestamp, self.timestamp, self.history_length)
        track.entered = in_zone(track.point, self.entry_zone)
        self.tracks[track_id] = track
        self.crossing_states[track_id] = CrossingState()
        self.crossing_states[track_id].update(track.point, self.timestamp, self.gate)
        self.reversal_states[track_id] = ReversalState(track.point)
        approach = self.gate.approach_distance(track.point)
        self.attempt_states[track_id] = AttemptState(approach, approach, approach)
        self.counts['tracks_produced'] += 1
        self._event('TRACK_STARTED', track, f'Fish #{track.id} acquired')
        return track

    def _attempt(self, track):
        track.attempts += 1
        self.counts['attempts'] += 1
        if track.attempts > 1:
            track.flags.add('MULTIPLE_ATTEMPTS')
            self.heatmaps.attempt(track.point)
        self._event('PASSAGE_ATTEMPT', track, f'Fish #{track.id} approaching passage · attempt {track.attempts}')

    def _success(self, track):
        if track.passage_seconds is not None:
            return
        track.status = 'PASSED'
        track.passage_seconds = self.timestamp - track.first_seen
        self.counts['successful'] += 1
        self.passage_times.append(track.passage_seconds)
        if not track.reversals and 'LONG_DWELL' not in track.flags:
            self.successful_dwell.append(track.dwell_time)
        self._event('PASSAGE_SUCCESS', track, f'Fish #{track.id} completed observed passage')

    def _archive(self, track_id):
        track = self.tracks.pop(track_id)
        if track.status == 'ACTIVE':
            track.status = 'INCOMPLETE'
        self.archived[track_id] = track
        while len(self.archived) > self.max_archived:
            self.archived.popitem(last=False)
        self.crossing_states.pop(track_id, None)
        self.reversal_states.pop(track_id, None)
        self.attempt_states.pop(track_id, None)
        self.completed_count += 1
        self._event('TRACK_ENDED', track, f'Fish #{track.id} left observation · {track.status.lower()}')

    def update(self, tracked, timestamp: float):
        if not math.isfinite(timestamp):
            raise ValueError('Behavior timestamps must be finite.')
        if self.started_at is not None and timestamp < self.timestamp:
            raise ValueError('Behavior timestamps must be monotonic; reset analysis when seeking.')
        if self.started_at is None:
            self.started_at = timestamp
        self.timestamp = float(timestamp)
        for track_id, track in list(self.tracks.items()):
            if timestamp - track.last_seen > 2.0:
                self._archive(track_id)
        for observation in tracked:
            track_id = int(observation['id'] if isinstance(observation, dict) else observation.id)
            bbox = observation['bbox'] if isinstance(observation, dict) else observation.bbox
            confidence = observation['confidence'] if isinstance(observation, dict) else observation.confidence
            if len(bbox) != 4 or not all(math.isfinite(value) for value in [*bbox, confidence]):
                continue
            if track_id not in self.tracks:
                # ByteTrack IDs are unique per session; a resumed ID after expiry
                # starts a fresh observation rather than bridging an unseen path.
                self._new_track(track_id, bbox, confidence)
                continue
            track = self.tracks[track_id]
            previous, elapsed = track.move(bbox, confidence, timestamp, self.upstream)
            if elapsed <= 0:
                continue
            track.entered = track.entered or in_zone(track.point, self.entry_zone)
            for key, seconds in residence_segments(previous, track.point, elapsed, self.heatmaps.columns, self.heatmaps.rows):
                track.residence[key] = track.residence.get(key, 0.0) + seconds
                self.heatmaps.density[key] += seconds
                self.heatmaps.dwell[key] = max(self.heatmaps.dwell[key], track.residence[key])
                if track.residence[key] >= self.long_dwell_limit:
                    self.heatmaps.friction[key] += seconds
                elif math.hypot(*track.velocity) < 0.02 and abs(self.gate.approach_distance(track.point)) < 0.18 and track.residence[key] > 2:
                    self.heatmaps.friction[key] += seconds * 0.15
            track.dwell_time = max(track.residence.values(), default=0.0)
            if track.dwell_time >= self.long_dwell_limit and 'LONG_DWELL' not in track.flags:
                track.flags.add('LONG_DWELL')
                self.counts['long_dwell'] += 1
                self._event('LONG_DWELL', track, f'Elevated dwell time · fish #{track.id}')
            reversal = self.reversal_states[track_id].update(track.point, track.velocity, confidence, timestamp, self.reversal_threshold)
            if reversal is not None:
                track.reversals += 1
                track.reversal_locations.append(reversal)
                track.flags.add('REVERSAL')
                if track.passage_seconds is None:
                    track.status = 'REVERSED'
                self.counts['reversals'] += 1
                self.heatmaps.reversal(reversal)
                self._event('REVERSAL', track, f'Reversal detected · fish #{track.id}', reversal)
            attempt_state = self.attempt_states[track_id]
            if attempt_state.update(track.point, track.direction, self.gate):
                self._attempt(track)
            crossing = self.crossing_states[track_id].update(track.point, timestamp, self.gate)
            if crossing:
                track.gate_crossings.append(crossing)
                self.counts[crossing['direction']] += 1
                self._event(f"{crossing['direction'].upper()}_CROSSING", track, f"Fish #{track.id} crossed {crossing['direction']}", crossing['position'])
                if crossing['direction'] == 'upstream':
                    if attempt_state.crossing_attempt():
                        self._attempt(track)
                    if track.entered and self.exit_zone is None:
                        self._success(track)
            if self.exit_zone is not None and track.entered and track.direction == 'upstream' and in_zone(track.point, self.exit_zone):
                self._success(track)
        # Cap live state too, so a busy or pathological feed cannot grow forever.
        if len(self.tracks) > 200:
            for track in sorted(self.tracks.values(), key=lambda item: item.last_seen)[:len(self.tracks) - 200]:
                self._archive(track.id)
        # A review cue: four recently observed tracks within a small local region
        # for at least 1.5 seconds. This is not a biological congestion diagnosis.
        recent = [t for t in self.tracks.values() if timestamp - t.last_seen < 0.5]
        cluster = []
        for candidate in recent:
            nearby = [t for t in recent if abs(t.point[0] - candidate.point[0]) < .09 and abs(t.point[1] - candidate.point[1]) < .12]
            if len(nearby) > len(cluster):
                cluster = nearby
        if len(cluster) >= 4:
            if self.congestion_since is None:
                self.congestion_since = timestamp
            if timestamp - self.congestion_since >= 1.5 and timestamp - self.last_congestion >= 15:
                self._event('CONGESTION', cluster[0], f'{len(cluster)} fish remain close together · review local movement')
                self.last_congestion = timestamp
        else:
            self.congestion_since = None
        return self.snapshot()

    def finish(self, timestamp: float | None = None):
        if timestamp is not None:
            self.timestamp = max(self.timestamp, float(timestamp))
        for track_id in list(self.tracks):
            self._archive(track_id)
        return self.snapshot()

    def snapshot(self):
        elapsed = max(0.0, self.timestamp - self.started_at) if self.started_at is not None else 0.0
        resolved = self.completed_count + sum(track.passage_seconds is not None for track in self.tracks.values())
        summary = {
            **self.counts, 'active': len(self.tracks),
            'passage_rate': round(self.counts['upstream'] / elapsed * 3600, 1) if elapsed > 0 else 0.0,
            'success_rate': round(self.counts['successful'] / resolved * 100, 1) if resolved else None,
            'median_passage_seconds': round(median(self.passage_times), 2) if self.passage_times else None,
            'elapsed_seconds': round(elapsed, 3),
        }
        return {
            'tracks': [track.serialize(False) for track in self.archived.values()] + [track.serialize(True) for track in self.tracks.values()],
            'summary': summary, 'events': list(self.events),
            'heatmaps': self.heatmaps.snapshot(self.baseline, self.long_dwell_limit),
        }
