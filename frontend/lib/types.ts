export type Point = [number, number];
export type Gate = [Point, Point];
export type ViewMode = "live" | "trajectories" | "behavior";
export type TrackFilter = "All" | "Upstream" | "Downstream" | "Reversals" | "Long dwell" | "Selected";
export interface Track {
  id: number;
  bbox: [number, number, number, number];
  centroid: Point;
  confidence: number;
  trajectory: [number, number, number][];
  smoothed_velocity: Point;
  velocity: number;
  direction: "upstream" | "downstream" | "uncertain";
  time_observed: number;
  reversals: number;
  reversal_locations: Point[];
  dwell_time: number;
  attempts: number;
  status: "ACTIVE" | "PASSED" | "REVERSED" | "INCOMPLETE";
  flags: string[];
  last_seen: number;
  active?: boolean;
}
export interface Session {
  id: string;
  mode: "LIVE_INFERENCE" | "PRECOMPUTED_DEMO" | "VISUALIZATION_DEMO";
  label: string;
  source_name: string;
  running: boolean;
  completed: boolean;
  error: string | null;
  detector_state: string;
  message?: string;
  video_url: string | null;
  original_video_url?: string | null;
  duration?: number;
  calibration_required?: boolean;
  width: number;
  height: number;
  calibration?: { upstream: Point; gate: Gate; entry_zone?: [number, number, number, number] | null; exit_zone?: [number, number, number, number] | null };
  source_type: "live" | "stream" | "upload" | "preprocessed" | "simulated";
  passage_calibrated: boolean;
  reconnecting: boolean;
  reconnect_attempts: number;
  display_fps: number;
}
export interface Summary {
  upstream: number;
  downstream: number;
  active: number;
  passage_rate: number | null;
  successful: number;
  attempts: number;
  reversals: number;
  long_dwell: number;
  success_rate: number | null;
  median_passage_seconds: number | null;
  elapsed_seconds: number;
  tracks_produced: number;
}
export interface PassageEvent {
  id: number | string;
  type: string;
  track_id: number;
  timestamp: number;
  position: Point;
  message: string;
}
export interface Snapshot {
  session: Session;
  frame: number;
  timestamp: number;
  processing_fps: number;
  tracks: Track[];
  summary: Summary;
  events: PassageEvent[];
  heatmaps: {
    density: number[][];
    friction: number[][];
    columns: number;
    rows: number;
    hotspot: null | { x: number; y: number; reversals: number; dwell_seconds: number; baseline_ratio: number | null };
  };
  simulation_fish?: { bbox: [number, number, number, number]; confidence: number; heading: number }[];
}
export const EMPTY_SUMMARY: Summary = {
  upstream: 0, downstream: 0, active: 0, passage_rate: null, successful: 0,
  attempts: 0, reversals: 0, long_dwell: 0, success_rate: null,
  median_passage_seconds: null, elapsed_seconds: 0, tracks_produced: 0,
};
export const DEFAULT_GATE: Gate = [[0.64, 0.18], [0.64, 0.84]];
