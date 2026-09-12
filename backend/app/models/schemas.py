from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator
import math

Point = tuple[float, float]


class SessionCreate(BaseModel):
    source: Literal['demo', 'visualization'] = 'demo'


class URLSource(BaseModel):
    url: str = Field(min_length=8, max_length=4096)


class Calibration(BaseModel):
    upstream: Point = (1., 0.)
    gate: tuple[Point, Point] = ((0.65, 0.26), (0.65, 0.74))
    entry_zone: tuple[float, float, float, float] | None = None
    exit_zone: tuple[float, float, float, float] | None = None

    @model_validator(mode='after')
    def valid_geometry(self):
        length = math.hypot(*self.upstream)
        if not math.isfinite(length) or length < 0.01:
            raise ValueError('Upstream direction must be a nonzero finite vector.')
        self.upstream = tuple(v / length for v in self.upstream)
        if any(not math.isfinite(v) or not 0 <= v <= 1 for p in self.gate for v in p):
            raise ValueError('Gate coordinates must be normalized within [0, 1].')
        dx, dy = self.gate[1][0] - self.gate[0][0], self.gate[1][1] - self.gate[0][1]
        if math.hypot(dx, dy) < 0.05:
            raise ValueError('Gate must span at least 5% of the frame.')
        if abs(dx * self.upstream[1] - dy * self.upstream[0]) / math.hypot(dx, dy) < 0.1:
            raise ValueError('Gate must cross the upstream direction, rather than run parallel to it.')
        for zone in (self.entry_zone, self.exit_zone):
            if zone and (any(not 0 <= v <= 1 for v in zone) or zone[0] >= zone[2] or zone[1] >= zone[3]):
                raise ValueError('Zones must be normalized rectangles [x1,y1,x2,y2].')
        return self


class CachedDetection(BaseModel):
    bbox: tuple[float, float, float, float]
    confidence: float = Field(ge=0, le=1)
    class_name: Literal['fish'] = 'fish'

    @model_validator(mode='after')
    def valid_box(self):
        if any(not 0 <= value <= 1 for value in self.bbox) or self.bbox[2] <= self.bbox[0] or self.bbox[3] <= self.bbox[1]:
            raise ValueError('Invalid normalized bounding box.')
        return self


class CachedFrame(BaseModel):
    frame: int = Field(ge=0)
    timestamp: float = Field(ge=0, allow_inf_nan=False)
    detections: list[CachedDetection]


class DetectionCache(BaseModel):
    schema_version: Literal[1] = 1
    provenance: Literal['fishial_local', 'local_yolo']
    model_id: str
    model_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    confidence_threshold: float = Field(default=.20, ge=0, le=1)
    video: str
    video_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    fps: float = Field(gt=0, allow_inf_nan=False)
    sample_fps: float = Field(gt=0, le=60, allow_inf_nan=False)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    total_frames: int = Field(gt=0)
    frames: list[CachedFrame] = Field(min_length=1)

    @model_validator(mode='after')
    def chronological(self):
        if any(b.frame <= a.frame or b.timestamp <= a.timestamp for a, b in zip(self.frames, self.frames[1:])):
            raise ValueError('Cache frames must have strictly increasing indices and timestamps.')
        if any(f.frame >= self.total_frames or abs(f.timestamp - f.frame / self.fps) > 1 / self.fps for f in self.frames):
            raise ValueError('Cache timestamps must correspond to source frame indices.')
        return self


class SourceState(BaseModel):
    id: str
    mode: Literal['LIVE_INFERENCE', 'PRECOMPUTED_DEMO', 'VISUALIZATION_DEMO']
    label: str
    source_name: str
    source_origin: str
    running: bool
    completed: bool
    error: str | None
    detector_state: str
    video_url: str | None
    original_video_url: str | None
    width: int
    height: int
    duration: float | None
    calibration_required: bool
    calibration: Calibration
    source_type: Literal['live', 'stream', 'upload', 'preprocessed', 'simulated']
    passage_calibrated: bool
    reconnecting: bool = False
    reconnect_attempts: int = 0
    display_fps: float = 0
    stream_active: bool = False


class Crossing(BaseModel):
    direction: Literal['upstream', 'downstream']
    timestamp: float
    position: Point


class TrackRecord(BaseModel):
    id: int
    bbox: tuple[float, float, float, float]
    centroid: Point
    confidence: float
    first_seen: float
    last_seen: float
    trajectory: list[tuple[float, float, float]]
    smoothed_velocity: Point
    velocity: float
    direction: Literal['upstream', 'downstream', 'uncertain']
    distance_traveled: float
    time_observed: float
    reversals: int
    reversal_locations: list[Point]
    dwell_time: float
    gate_crossings: list[Crossing]
    attempts: int
    status: Literal['ACTIVE', 'PASSED', 'REVERSED', 'INCOMPLETE']
    flags: list[str]
    active: bool
    passage_seconds: float | None


class PassageSummary(BaseModel):
    upstream: int
    downstream: int
    successful: int
    attempts: int
    reversals: int
    long_dwell: int
    tracks_produced: int
    active: int
    passage_rate: float | None
    success_rate: float | None
    median_passage_seconds: float | None
    elapsed_seconds: float


class PassageEvent(BaseModel):
    id: int
    type: Literal['TRACK_STARTED', 'TRACK_ENDED', 'UPSTREAM_CROSSING', 'DOWNSTREAM_CROSSING', 'PASSAGE_ATTEMPT', 'PASSAGE_SUCCESS', 'REVERSAL', 'LONG_DWELL', 'CONGESTION']
    track_id: int
    timestamp: float
    position: Point
    message: str


class Hotspot(BaseModel):
    x: float
    y: float
    reversals: int
    dwell_seconds: float
    baseline_ratio: float | None


class HeatmapState(BaseModel):
    density: list[list[float]]
    friction: list[list[float]]
    rows: int
    columns: int
    hotspot: Hotspot | None


class Snapshot(BaseModel):
    """Detector-neutral API protocol; JSON schemas document the complete payload."""
    session: SourceState
    frame: int
    timestamp: float
    processing_fps: float
    tracks: list[TrackRecord]
    summary: PassageSummary
    events: list[PassageEvent]
    heatmaps: HeatmapState
    simulation_fish: list[dict] = Field(default_factory=list)
