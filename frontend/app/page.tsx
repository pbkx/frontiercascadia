"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Check, Crosshair,
  LoaderCircle, Pause, Play, Radio, Settings2, Upload, WifiOff, X,
} from "lucide-react";
import ObservationCanvas from "@/components/ObservationCanvas";
import { api, backendUrl } from "@/lib/api";
import {
  DEFAULT_GATE, EMPTY_SUMMARY, type Gate, type Point, type Snapshot,
  type Track, type TrackFilter, type ViewMode,
} from "@/lib/types";

const FILTERS: TrackFilter[] = ["All", "Upstream", "Downstream", "Reversals", "Long dwell", "Selected"];
const DIRECTIONS: { name: string; vector: Point; icon: typeof ArrowUp }[] = [
  { name: "Left", vector: [-1, 0], icon: ArrowLeft },
  { name: "Right", vector: [1, 0], icon: ArrowRight },
  { name: "Up", vector: [0, -1], icon: ArrowUp },
  { name: "Down", vector: [0, 1], icon: ArrowDown },
];

function defaultZones(direction: Point) {
  if (direction[0] > 0) return { entry: [0, 0, .18, 1], exit: [.82, 0, 1, 1] };
  if (direction[0] < 0) return { entry: [.82, 0, 1, 1], exit: [0, 0, .18, 1] };
  if (direction[1] > 0) return { entry: [0, 0, 1, .18], exit: [0, .82, 1, 1] };
  return { entry: [0, .82, 1, 1], exit: [0, 0, 1, .18] };
}

export default function SalmonSight() {
  const [packet, setPacket] = useState<Snapshot | null>(null);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [connecting, setConnecting] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<ViewMode>("live");
  const [filter, setFilter] = useState<TrackFilter>("All");
  const [heatmap, setHeatmap] = useState<"density" | "friction">("density");
  const [selected, setSelected] = useState<number | null>(null);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [calibrating, setCalibrating] = useState(false);
  const [url, setUrl] = useState("");
  const [gate, setGate] = useState<Gate>(DEFAULT_GATE);
  const [upstream, setUpstream] = useState<Point>([1, 0]);
  const [passageZones, setPassageZones] = useState(false);
  const [boxes, setBoxes] = useState(true);
  const [trails, setTrails] = useState(true);
  const histories = useRef(new Map<number, Track>());
  const initialized = useRef(false);
  const currentSession = useRef<string | null>(null);
  const lastTimestamp = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);

  const session = packet?.session;
  const summary = packet?.summary ?? EMPTY_SUMMARY;
  const selectedTrack = tracks.find(track => track.id === selected);
  const averageDwell = tracks.length ? tracks.reduce((total, track) => total + track.dwell_time, 0) / tracks.length : 0;

  const acceptPacket = useCallback((next: Snapshot) => {
    if (!next?.session || !next.summary) return;
    if (currentSession.current !== next.session.id || next.timestamp < lastTimestamp.current) {
      histories.current.clear();
      setSelected(null);
      if (next.session.calibration) {
        setGate(next.session.calibration.gate);
        setUpstream(next.session.calibration.upstream);
        setPassageZones(Boolean(next.session.calibration.entry_zone && next.session.calibration.exit_zone));
      }
    }
    currentSession.current = next.session.id;
    lastTimestamp.current = next.timestamp;
    for (const track of next.tracks || []) {
      const previous = histories.current.get(track.id);
      const incoming = track.trajectory || [];
      const trajectory = previous && incoming.length
        ? [...previous.trajectory.filter(point => point[2] < incoming[0][2]), ...incoming].slice(-600)
        : incoming.length ? incoming : previous?.trajectory || [];
      histories.current.set(track.id, { ...track, trajectory });
    }
    if (histories.current.size > 500) {
      for (const [id, track] of histories.current) {
        if (!track.active && histories.current.size > 500) histories.current.delete(id);
      }
    }
    setTracks([...histories.current.values()]);
    setPacket(next);
  }, []);

  const createDefault = useCallback(async () => {
    setConnecting(true);
    setError(null);
    try {
      const oldId = currentSession.current;
      const next = await api<Snapshot>("/api/sessions", {
        method: "POST",
        body: JSON.stringify({ source: "demo" }),
        signal: AbortSignal.timeout(45000),
      });
      acceptPacket(next);
      if (oldId && oldId !== next.session.id) void api(`/api/sessions/${oldId}`, { method: "DELETE" }).catch(() => undefined);
      setSourceOpen(false);
      setMode("live");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to connect to this stream. Try again or choose another source.");
    } finally {
      setConnecting(false);
    }
  }, [acceptPacket]);

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    void createDefault();
  }, [createDefault]);

  useEffect(() => {
    if (!session?.id) return;
    let disposed = false;
    let retry: ReturnType<typeof setTimeout>;
    let socket: WebSocket | null = null;
    const connect = () => {
      if (disposed) return;
      socket = new WebSocket(`${backendUrl().replace(/^http/, "ws")}/ws/sessions/${session.id}`);
      socket.onmessage = event => { try { acceptPacket(JSON.parse(event.data)); } catch { /* retain last valid state */ } };
      socket.onclose = () => {
        if (!disposed) retry = setTimeout(connect, 2000);
      };
    };
    connect();
    return () => { disposed = true; clearTimeout(retry); socket?.close(); };
  }, [session?.id, acceptPacket]);

  const ensureSession = async () => {
    if (session?.id) return session.id;
    const placeholder = await api<Snapshot>("/api/sessions", { method: "POST", body: JSON.stringify({ source: "visualization" }) });
    acceptPacket(placeholder);
    return placeholder.session.id;
  };

  const connectUrl = async () => {
    if (!url.trim()) { setError("Enter a YouTube, HLS, HTTP, or RTSP stream URL."); return; }
    setBusy(true); setError(null);
    try {
      const id = await ensureSession();
      const next = await api<Snapshot>(`/api/sessions/${id}/source/url`, {
        method: "POST", body: JSON.stringify({ url: url.trim() }), signal: AbortSignal.timeout(45000),
      });
      histories.current.clear(); acceptPacket(next);
      setSourceOpen(false); setSettingsOpen(true); setCalibrating(true); setMode("live");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to connect to this stream. Try again or choose another source.");
    } finally { setBusy(false); }
  };

  const upload = async (file: File) => {
    if (!/\.(mp4|mov|avi)$/i.test(file.name)) { setError("Upload an MP4, MOV, or AVI video."); return; }
    setBusy(true); setError(null);
    try {
      const id = await ensureSession();
      const form = new FormData(); form.append("file", file);
      const next = await api<Snapshot>(`/api/sessions/${id}/source`, {
        method: "POST", body: form, signal: AbortSignal.timeout(120000),
      });
      histories.current.clear(); acceptPacket(next);
      setSourceOpen(false); setSettingsOpen(true); setCalibrating(true); setMode("live");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The uploaded video could not be opened.");
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const saveCalibration = async () => {
    if (!session) return;
    setBusy(true); setError(null);
    const zones = defaultZones(upstream);
    try {
      let next = await api<Snapshot>(`/api/sessions/${session.id}/calibration`, {
        method: "POST",
        body: JSON.stringify({
          upstream, gate,
          entry_zone: passageZones ? zones.entry : null,
          exit_zone: passageZones ? zones.exit : null,
        }),
      });
      histories.current.clear(); acceptPacket(next);
      next = await api<Snapshot>(`/api/sessions/${session.id}/start`, { method: "POST" });
      acceptPacket(next);
      setSettingsOpen(false); setCalibrating(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Calibration could not be saved.");
    } finally { setBusy(false); }
  };

  const toggleAnalysis = async () => {
    if (!session) { void createDefault(); return; }
    setBusy(true); setError(null);
    try {
      acceptPacket(await api<Snapshot>(`/api/sessions/${session.id}/${session.running ? "pause" : "start"}`, { method: "POST" }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Analysis could not be changed.");
    } finally { setBusy(false); }
  };

  const videoUrl = session?.video_url ? `${session.video_url.startsWith("http") ? "" : backendUrl()}${session.video_url}` : null;
  const stateText = session?.reconnecting ? "RECONNECTING" : session?.label || "NO SOURCE";
  const isActivelyLive = session?.source_type === "live" && session.stream_active;

  return <main className={`app mode-${mode}`}>
    <div className="video-stage">
      {videoUrl && <img className="video-layer" src={videoUrl} alt="Current fish camera video" /> /* eslint-disable-line @next/next/no-img-element */}
      {!videoUrl && <div className="video-empty">
        {connecting
          ? <div className="video-loading" role="status" aria-label="Loading video"><LoaderCircle className="spin video-loader" size={30} /></div>
          : <><Radio size={26} /><span>Video source unavailable</span><small>Choose another source to continue.</small></>}
      </div>}
    </div>
    <div className="video-dim" />
    <ObservationCanvas
      packet={packet} tracks={tracks} mode={mode} filter={filter} heatmap={heatmap}
      selected={selected} onSelect={setSelected} gate={gate} calibrating={calibrating}
      onGateChange={setGate} showBoxes={boxes} showTrails={trails}
    />

    <header className="topbar">
      {session && <div className="source-origin" title={session.source_origin}>{session.source_origin}</div>}
      {session && <div className="source-state">
        {isActivelyLive
          ? <strong className="live-status"><i aria-hidden="true" />LIVE</strong>
          : <strong>{session.source_type === "live" && !session.reconnecting ? "OFFLINE" : stateText}</strong>}
        <span>{(packet?.processing_fps || 0).toFixed(1)} FPS</span>
      </div>}
    </header>

    {mode === "trajectories" && <div className="mode-tools glass" role="group" aria-label="Trajectory filters">
      {FILTERS.map(value => <button key={value} className={filter === value ? "active" : ""} onClick={() => setFilter(value)}>{value}</button>)}
    </div>}

    {mode === "behavior" && <div className="mode-tools glass" role="group" aria-label="Heatmap type">
      <button className={heatmap === "density" ? "active" : ""} onClick={() => setHeatmap("density")}>Movement density</button>
      <button className={heatmap === "friction" ? "active" : ""} onClick={() => setHeatmap("friction")}>Reversal / dwell hotspot</button>
    </div>}

    <section className="metrics glass" aria-label="Tracking metrics">
      <div><span>Upstream crossings</span><strong>{summary.upstream}</strong></div>
      <div><span>Downstream crossings</span><strong>{summary.downstream}</strong></div>
      <div><span>Active fish</span><strong>{summary.active}</strong></div>
      <div><span>Reversals</span><strong>{summary.reversals}</strong></div>
      <div><span>Average dwell</span><strong>{averageDwell ? `${averageDwell.toFixed(1)}s` : "—"}</strong></div>
      {session?.passage_calibrated && <div><span>Passage success</span><strong>{summary.success_rate === null ? "—" : `${Math.round(summary.success_rate)}%`}</strong></div>}
      {session?.passage_calibrated && <div><span>Passage attempts</span><strong>{summary.attempts}</strong></div>}
    </section>

    {session?.passage_calibrated && <div className="rate-note glass">Passage rate: {summary.passage_rate === null ? "Collecting data…" : `${Math.round(summary.passage_rate)} fish/hour`}</div>}

    {selectedTrack && <aside className="track-panel glass" aria-label={`Fish ${selectedTrack.id} details`}>
      <button aria-label="Close fish details" onClick={() => setSelected(null)}><X size={14} /></button>
      <strong>Fish #{selectedTrack.id}</strong><span>{selectedTrack.confidence.toFixed(2)}</span>
      <dl><div><dt>Direction</dt><dd>{selectedTrack.direction}</dd></div><div><dt>Dwell time</dt><dd>{selectedTrack.dwell_time.toFixed(1)}s</dd></div><div><dt>Reversals</dt><dd>{selectedTrack.reversals}</dd></div><div><dt>Observed</dt><dd>{selectedTrack.time_observed.toFixed(1)}s</dd></div></dl>
    </aside>}

    <div className="bottom-ui">
      <button className="analysis-button glass" onClick={() => void toggleAnalysis()} disabled={busy || connecting || calibrating} aria-label={session?.running ? "Pause analysis" : "Start analysis"}>
        {busy || connecting ? <LoaderCircle className="spin" size={15} /> : session?.running ? <Pause size={14} /> : <Play size={14} />}
        {session?.running ? "Pause" : "Analyze"}
      </button>
      <nav className="view-switch glass" aria-label="Main modes">
        {(["live", "trajectories", "behavior"] as ViewMode[]).map(value => <button key={value} className={mode === value ? "active" : ""} aria-pressed={mode === value} onClick={() => setMode(value)}>{value}</button>)}
      </nav>
      <button className="change-source glass" onClick={() => setSourceOpen(true)}>Change source</button>
      <button className="settings-button glass" aria-label="Open calibration settings" onClick={() => { setSettingsOpen(true); setCalibrating(true); }}><Settings2 size={15} /></button>
    </div>

    {session?.completed && <div className="notice glass">Uploaded video ended. Choose replay or another source.</div>}
    {(error || session?.error) && <div className="error-banner glass" role="alert"><WifiOff size={15} /><span>{error || session?.error}</span><button aria-label="Dismiss error" onClick={() => setError(null)}><X size={14} /></button></div>}

    {settingsOpen && <aside className="settings-panel glass" aria-label="Calibration settings">
      <div className="panel-title"><strong>Calibration</strong><button aria-label="Close calibration settings" onClick={() => { setSettingsOpen(false); setCalibrating(false); }}><X size={16} /></button></div>
      <label>Upstream direction</label>
      <div className="direction-grid">{DIRECTIONS.map(direction => <button key={direction.name} aria-label={`Upstream ${direction.name.toLowerCase()}`} className={upstream[0] === direction.vector[0] && upstream[1] === direction.vector[1] ? "active" : ""} onClick={() => setUpstream(direction.vector)}><direction.icon size={17} /><span>{direction.name}</span></button>)}</div>
      <button className="line-control" onClick={() => setCalibrating(value => !value)}><Crosshair size={14} />{calibrating ? "Drag counting line endpoints" : "Adjust counting line"}</button>
      <label className="check-row"><input type="checkbox" checked={passageZones} onChange={event => setPassageZones(event.target.checked)} /><span>Use entry and exit areas</span></label>
      <small>Enable only when the footage clearly shows both areas. This unlocks passage success and attempt metrics.</small>
      <label className="check-row"><input type="checkbox" checked={boxes} onChange={event => setBoxes(event.target.checked)} /><span>Bounding boxes</span></label>
      <label className="check-row"><input type="checkbox" checked={trails} onChange={event => setTrails(event.target.checked)} /><span>Short trails</span></label>
      <button className="save-calibration" onClick={() => void saveCalibration()} disabled={busy}>{busy ? <LoaderCircle className="spin" size={14} /> : <Check size={14} />} Save calibration</button>
    </aside>}

    {sourceOpen && <div className="modal-backdrop" onClick={() => setSourceOpen(false)}>
      <section className="source-modal glass" role="dialog" aria-modal="true" aria-labelledby="source-title" onClick={event => event.stopPropagation()}>
        <div className="panel-title"><h2 id="source-title">Source</h2><button aria-label="Close source panel" onClick={() => setSourceOpen(false)}><X size={17} /></button></div>
        <button className="default-source" disabled={busy || connecting} onClick={() => void createDefault()}><Radio size={17} /><span><strong>Issaquah SalmonCam</strong><small>Default YouTube live stream</small></span></button>
        <div className="or"><span>or</span></div>
        <label htmlFor="stream-url">YouTube / stream URL</label>
        <input id="stream-url" value={url} onChange={event => setUrl(event.target.value)} placeholder="https://www.youtube.com/watch?v=…" />
        <button className="connect-button" disabled={busy} onClick={() => void connectUrl()}>{busy ? <LoaderCircle className="spin" size={14} /> : <Activity size={14} />} Connect</button>
        <div className="or"><span>or</span></div>
        <button className="upload-button" disabled={busy} onClick={() => fileInput.current?.click()}><Upload size={15} /> Upload MP4 / MOV</button>
        <small className="source-help">MP4, MOV, and supported AVI files run through the same local detector and tracker.</small>
      </section>
    </div>}

    <input ref={fileInput} className="file-input" type="file" accept="video/mp4,video/quicktime,video/x-msvideo,.mp4,.mov,.avi" onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file); }} />
  </main>;
}
