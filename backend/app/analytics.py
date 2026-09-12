"""Deterministic, range-filtered aggregations over existing track/event data."""

from __future__ import annotations

from collections import Counter
import math
from statistics import median


RANGES = {'5m': 300., '15m': 900., '1h': 3600., 'all': None, 'full': None}


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def rounded(value: float | None, digits: int = 2):
    return round(value, digits) if value is not None and math.isfinite(value) else None


def duration_label(seconds: float) -> str:
    seconds = max(0, round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f'{hours}h {minutes}m'
    if minutes:
        return f'{minutes}m {seconds}s'
    return f'{seconds}s'


def histogram(values: list[float], boundaries: list[float], *, speed=False) -> list[dict]:
    bins = []
    for index, lower in enumerate(boundaries):
        upper = boundaries[index + 1] if index + 1 < len(boundaries) else None
        count = sum(lower <= value < upper if upper is not None else value >= lower for value in values)
        number = lambda value: f'{value:.2f}'.rstrip('0').rstrip('.') if speed else f'{value:g}'
        label = f'{number(lower)}–{number(upper)}' if upper is not None else f'{number(lower)}+'
        bins.append({'label': label, 'min': lower, 'max': upper, 'count': count})
    return bins


def group_metrics(tracks: list[dict]) -> dict:
    observed = [max(0., float(track.get('time_observed') or 0)) for track in tracks]
    speeds = [float(track.get('velocity') or 0) for track in tracks if float(track.get('velocity') or 0) > 0]
    distances = [max(0., float(track.get('distance_traveled') or 0)) for track in tracks]
    crossed = sum(any(crossing.get('direction') == 'upstream' for crossing in track.get('gate_crossings', [])) for track in tracks)
    return {
        'count': len(tracks),
        'median_observed_time': rounded(median(observed) if observed else None),
        'median_relative_speed': rounded(median(speeds) if speeds else None, 3),
        'median_distance': rounded(median(distances) if distances else None, 3),
        'upstream_crossing_rate': rounded(crossed / len(tracks) * 100 if tracks else None, 1),
    }


def build_analytics(snapshot: dict, selected_range: str = 'all') -> dict:
    if selected_range not in RANGES:
        raise ValueError('Range must be one of: 5m, 15m, 1h, all, full.')
    current = max(0., float(snapshot.get('timestamp') or 0))
    window = RANGES[selected_range]
    cutoff = max(0., current - window) if window else 0.
    all_tracks = snapshot.get('tracks') or []
    tracks = [track for track in all_tracks if float(track.get('last_seen') or 0) >= cutoff and float(track.get('first_seen') or 0) <= current]
    events = [event for event in snapshot.get('events') or [] if cutoff <= float(event.get('timestamp') or 0) <= current]
    observed = [max(0., float(track.get('time_observed') or 0)) for track in tracks]
    speeds = [float(track.get('velocity') or 0) for track in tracks if float(track.get('velocity') or 0) > 0]
    directions = Counter(track.get('direction', 'uncertain') if track.get('direction') in {'upstream', 'downstream'} else 'uncertain' for track in tracks)
    total = len(tracks)
    reversal_tracks = [track for track in tracks if int(track.get('reversals') or 0) > 0]
    normal_tracks = [track for track in tracks if int(track.get('reversals') or 0) == 0]

    summary = {
        'fish_tracked': total,
        'upstream_percent': rounded(directions['upstream'] / total * 100 if total else None, 1),
        'downstream_percent': rounded(directions['downstream'] / total * 100 if total else None, 1),
        'reversal_rate': rounded(len(reversal_tracks) / total * 100 if total else None, 1),
        'median_observed_time': rounded(median(observed) if observed else None),
        'median_relative_speed': rounded(median(speeds) if speeds else None, 3),
    }

    span = max(0., current - cutoff)
    bucket_seconds = 30 if span <= 900 else 60 if span <= 7200 else 300 if span <= 21600 else 900
    bucket_count = max(1, math.ceil(span / bucket_seconds)) if current or tracks else 0
    activity = []
    behavior = []
    for index in range(bucket_count):
        start = cutoff + index * bucket_seconds
        end = min(current, start + bucket_seconds)
        track_starts = [track for track in tracks if start <= max(cutoff, float(track.get('first_seen') or 0)) < start + bucket_seconds]
        bucket_events = [event for event in events if start <= float(event.get('timestamp') or 0) < start + bucket_seconds]
        activity.append({
            'start': rounded(start), 'end': rounded(end), 'fish_observed': len(track_starts),
            'upstream_crossings': sum(event.get('type') == 'UPSTREAM_CROSSING' for event in bucket_events),
            'downstream_crossings': sum(event.get('type') == 'DOWNSTREAM_CROSSING' for event in bucket_events),
        })
        behavior.append({
            'start': rounded(start), 'end': rounded(end),
            'reversals': sum(event.get('type') == 'REVERSAL' for event in bucket_events),
            'long_dwell': sum(event.get('type') == 'LONG_DWELL' for event in bucket_events),
        })

    max_observed = max(observed, default=0)
    duration_boundaries = [0., 2., 4., 6., 10.] if max_observed <= 10 else [0., 5., 10., 20., 30.] if max_observed <= 30 else [0., 10., 30., 60., 120.]
    speed_ceiling = percentile(speeds, .9) or max(speeds, default=0)
    speed_step = max(.01, speed_ceiling / 4) if speed_ceiling else .05
    speed_boundaries = [round(speed_step * index, 4) for index in range(5)]
    normal = group_metrics(normal_tracks)
    reversal = group_metrics(reversal_tracks)

    findings = []
    directional = directions['upstream'] + directions['downstream']
    if directional >= 3:
        dominant = 'upstream' if directions['upstream'] >= directions['downstream'] else 'downstream'
        findings.append(f"{round(directions[dominant] / directional * 100)}% of directional tracks moved {dominant}.")
    if reversal_tracks:
        findings.append(f"{len(reversal_tracks)} fish {'showed' if len(reversal_tracks) == 1 else 'showed'} reversal behavior during this period.")
    if activity and max(item['fish_observed'] for item in activity) > 0:
        peak = max(activity, key=lambda item: item['fish_observed'])
        findings.append(f"Peak activity began {duration_label(peak['start'])} into the observation, with {peak['fish_observed']} fish first observed in {duration_label(bucket_seconds)}.")
    if normal['count'] >= 2 and reversal['count'] >= 2 and normal['median_observed_time'] and reversal['median_observed_time']:
        ratio = reversal['median_observed_time'] / normal['median_observed_time']
        if ratio >= 1.2:
            findings.append(f"Fish showing reversal behavior remained visible {ratio:.1f}× longer than tracks without reversals.")
        elif ratio <= .8:
            findings.append(f"Tracks without reversals remained visible {1 / ratio:.1f}× longer than reversal tracks.")
    if summary['median_relative_speed'] is not None and len(findings) < 5:
        findings.append(f"Median relative movement speed was {summary['median_relative_speed']:.3f} frame widths per second.")

    rows = []
    for track in tracks:
        crossings = track.get('gate_crossings') or []
        rows.append({
            'id': int(track['id']), 'display_id': int(track.get('display_id', track['id'])),
            'direction': track.get('direction', 'uncertain'),
            'observed_time': rounded(max(0., float(track.get('time_observed') or 0))),
            'relative_speed': rounded(max(0., float(track.get('velocity') or 0)), 3),
            'distance': rounded(max(0., float(track.get('distance_traveled') or 0)), 3),
            'reversals': int(track.get('reversals') or 0),
            'crossed': bool(crossings), 'first_seen': rounded(float(track.get('first_seen') or 0)),
        })

    return {
        'session_id': snapshot['session']['id'], 'source_type': snapshot['session']['source_type'],
        'source_name': snapshot['session']['source_name'],
        'range': selected_range,
        'observation': {'start': rounded(cutoff), 'end': rounded(current), 'seconds': rounded(span), 'bucket_seconds': bucket_seconds},
        'summary': summary, 'findings': findings[:5], 'activity': activity, 'behavior_events': behavior,
        'direction': [
            {'name': name, 'count': directions[name], 'percent': rounded(directions[name] / total * 100 if total else 0., 1)}
            for name in ('upstream', 'downstream', 'uncertain')
        ],
        'observed_time_distribution': histogram(observed, duration_boundaries),
        'observed_time_stats': {
            'median': rounded(median(observed) if observed else None),
            'p90': rounded(percentile(observed, .9)), 'longest': rounded(max(observed) if observed else None),
        },
        'speed_distribution': histogram(speeds, speed_boundaries, speed=True) if speeds else [],
        'speed_stats': {'median': rounded(median(speeds) if speeds else None, 3), 'p90': rounded(percentile(speeds, .9), 3)},
        'normal_vs_reversal': {'normal': normal, 'reversal': reversal},
        'scatter': [
            {'id': int(track['id']), 'display_id': int(track.get('display_id', track['id'])),
             'speed': rounded(float(track.get('velocity') or 0), 3),
             'observed_time': rounded(float(track.get('time_observed') or 0)), 'reversal': int(track.get('reversals') or 0) > 0}
            for track in tracks if float(track.get('velocity') or 0) > 0 and float(track.get('time_observed') or 0) > 0
        ],
        'tracks': rows,
    }
