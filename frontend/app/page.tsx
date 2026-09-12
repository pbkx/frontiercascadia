"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Activity, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Check, ChevronDown, CircleHelp, Crosshair, Eye, Fish, Focus, Gauge, GitBranch, Layers, LoaderCircle, Maximize2, Pause, Play, Radio, RotateCcw, Settings2, SlidersHorizontal, Sparkles, Upload, Waves, Wifi, WifiOff, X } from "lucide-react";
import ObservationCanvas from "@/components/ObservationCanvas";
import { api, backendUrl, formatTime } from "@/lib/api";
import { DEFAULT_GATE, EMPTY_SUMMARY, type Gate, type Point, type Snapshot, type Track, type TrackFilter, type ViewMode } from "@/lib/types";

const FILTERS: TrackFilter[] = ["All", "Successful", "Reversals", "Long dwell", "Selected"];
const DIRECTIONS: { name: string; vector: Point; icon: typeof ArrowUp }[] = [
  { name: "Left", vector: [-1, 0], icon: ArrowLeft }, { name: "Up", vector: [0, -1], icon: ArrowUp },
  { name: "Right", vector: [1, 0], icon: ArrowRight }, { name: "Down", vector: [0, 1], icon: ArrowDown },
];

function Metric({ label, value, children, accent = false }: { label: string; value: React.ReactNode; children?: React.ReactNode; accent?: boolean }) {
  return <div className={`metric-row ${accent ? "accent" : ""}`}><span>{children}{label}</span><strong>{value}</strong></div>;
}

export default function Observatory() {
  const [packet, setPacket] = useState<Snapshot | null>(null);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<ViewMode>("live");
  const [filter, setFilter] = useState<TrackFilter>("All");
  const [heatmap, setHeatmap] = useState<"density" | "friction">("friction");
  const [selected, setSelected] = useState<number | null>(null);
  const [modal, setModal] = useState<"source" | "help" | null>(null);
  const [settings, setSettings] = useState(false);
  const [calibrating, setCalibrating] = useState(false);
  const [gate, setGate] = useState<Gate>(DEFAULT_GATE);
  const [upstream, setUpstream] = useState<Point>([1, 0]);
  const [boxes, setBoxes] = useState(true);
  const [trails, setTrails] = useState(true);
  const [toast, setToast] = useState<string | null>(null);
  const [dropActive, setDropActive] = useState(false);
  const histories = useRef(new Map<number, Track>());
  const currentSession = useRef<string | null>(null);
  const lastTimestamp = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const summary = packet?.summary ?? EMPTY_SUMMARY;
  const session = packet?.session;
  const running = session?.running ?? false;
  const started = (packet?.timestamp ?? 0) > 0;
  const simulated = !session || session.mode === "VISUALIZATION_DEMO";
  const selectedTrack = tracks.find(t => t.id === selected);

  const acceptPacket = useCallback((next: Snapshot) => {
    if (!next?.session || !next.summary) return;
    if (currentSession.current !== next.session.id || next.timestamp < lastTimestamp.current) {
      histories.current.clear(); setSelected(null);
      if (next.session.calibration) { setGate(next.session.calibration.gate); setUpstream(next.session.calibration.upstream); }
    }
    currentSession.current = next.session.id; lastTimestamp.current = next.timestamp;
    for (const track of next.tracks || []) {
      const previous = histories.current.get(track.id);
      const incoming = track.trajectory || [];
      let trajectory = incoming;
      if (previous && incoming.length > 0) {
        trajectory = [...previous.trajectory.filter(point => point[2] < incoming[0][2]), ...incoming].slice(-600);
      } else if (previous) trajectory = previous.trajectory;
      histories.current.set(track.id, { ...track, trajectory });
    }
    // Bound browser memory during long camera sessions as well as each track history.
    if (histories.current.size > 500) {
      for (const [id, track] of histories.current) { if (!track.active && histories.current.size > 500) histories.current.delete(id); }
    }
    setTracks([...histories.current.values()]); setPacket(next);
  }, []);

  const initialize = useCallback(async () => {
    setConnecting(true); setError(null);
    try { acceptPacket(await api<Snapshot>("/api/sessions", { method: "POST", body: JSON.stringify({ source: "demo" }) })); }
    catch { setError("The analysis engine is offline. The illustrated habitat is available; start the backend to track fish."); }
    finally { setConnecting(false); }
  }, [acceptPacket]);

  useEffect(() => { void initialize(); }, [initialize]);
  useEffect(() => {
    if (!session?.id) return;
    let disposed = false, retry: ReturnType<typeof setTimeout>;
    const connect = () => {
      if (disposed) return;
      const socket = new WebSocket(`${backendUrl().replace(/^http/, "ws")}/ws/sessions/${session.id}`);
      socketRef.current = socket;
      socket.onopen = () => { setConnected(true); setError(null); };
      socket.onmessage = event => { try { acceptPacket(JSON.parse(event.data)); } catch { /* Keep the last valid frame when a packet is interrupted. */ } };
      socket.onerror = () => { setConnected(false); };
      socket.onclose = () => { if (!disposed) { setConnected(false); retry = setTimeout(connect, 2500); } };
    };
    connect();
    return () => { disposed = true; clearTimeout(retry); socketRef.current?.close(); };
  }, [session?.id, acceptPacket]);
  useEffect(() => { if (!toast) return; const timeout = setTimeout(() => setToast(null), 5000); return () => clearTimeout(timeout); }, [toast]);

  const toggleAnalysis = async () => {
    if (!session) { await initialize(); return; }
    setBusy(true); setError(null);
    try { acceptPacket(await api<Snapshot>(`/api/sessions/${session.id}/${running ? "pause" : "start"}`, { method: "POST" })); }
    catch (err) { setError(err instanceof Error ? err.message : "Analysis could not start."); }
    finally { setBusy(false); }
  };

  const chooseSource = async (source: "demo" | "visualization") => {
    setBusy(true); setError(null);
    try {
      if (session?.running) await api(`/api/sessions/${session.id}/pause`, { method: "POST" });
      const next = await api<Snapshot>("/api/sessions", { method: "POST", body: JSON.stringify({ source }) });
      acceptPacket(next); setModal(null); setMode("live"); setFilter("All");
      if (source === "demo" && next.session.mode === "VISUALIZATION_DEMO") setToast("No local Issaquah footage is configured. Showing clearly labeled simulated data.");
    } catch (err) { setError(err instanceof Error ? err.message : "The source could not be opened."); }
    finally { setBusy(false); }
  };

  const upload = async (file: File) => {
    if (!/\.(mp4|mov|avi)$/i.test(file.name)) { setError("Choose an MP4, MOV or AVI video."); return; }
    setBusy(true); setError(null);
    try {
      let id = session?.id;
      if (!id) { const next = await api<Snapshot>("/api/sessions", { method: "POST", body: JSON.stringify({ source: "visualization" }) }); id = next.session.id; acceptPacket(next); }
      const form = new FormData(); form.append("file", file);
      const next = await api<Snapshot>(`/api/sessions/${id}/source`, { method: "POST", body: form, signal: AbortSignal.timeout(120000) });
      histories.current.clear(); acceptPacket(next); setModal(null); setSettings(true); setCalibrating(true); setMode("live");
      setToast("Footage loaded. Set upstream direction and drag the gate before starting analysis.");
    } catch (err) { setError(err instanceof Error ? err.message : "The video could not be opened."); }
    finally { setBusy(false); if (fileInput.current) fileInput.current.value = ""; }
  };

  const saveCalibration = async () => {
    if (!session) { setError("Connect the analysis engine before saving calibration."); return; }
    setBusy(true);
    try {
      const next = await api<Snapshot>(`/api/sessions/${session.id}/calibration`, { method: "POST", body: JSON.stringify({ upstream, gate }) });
      histories.current.clear(); acceptPacket(next); setCalibrating(false); setSettings(false); setToast("Calibration saved. Start analysis to apply this passage geometry.");
    } catch (err) { setError(err instanceof Error ? err.message : "Calibration could not be saved."); }
    finally { setBusy(false); }
  };

  const closeSettings = () => {
    if (session?.calibration) { setGate(session.calibration.gate); setUpstream(session.calibration.upstream); }
    setSettings(false); setCalibrating(false);
  };

  const events = [...(packet?.events ?? [])].sort((a, b) => b.timestamp - a.timestamp).filter(e => !["TRACK_STARTED", "TRACK_ENDED", "PASSAGE_ATTEMPT"].includes(e.type)).slice(0, 2);
  const hotspot = packet?.heatmaps.hotspot;
  const sourceTitle = simulated ? "A river, reimagined." : session?.source_name || "Passage observation";
  const upstreamDirection = DIRECTIONS.find(d => d.vector[0] === upstream[0] && d.vector[1] === upstream[1]);
  const DirectionIcon = upstreamDirection?.icon ?? ArrowRight;

  return <main className={`observatory mode-${mode}`}>
    {session?.video_url && !simulated && <img className="video-layer" src={`${session.video_url.startsWith("http") ? "" : backendUrl()}${session.video_url}`} alt="Current video frame from the selected fish passage source" /> /* eslint-disable-line @next/next/no-img-element */}
    <ObservationCanvas packet={packet} tracks={tracks} mode={mode} filter={filter} heatmap={heatmap} selected={selected} onSelect={setSelected} gate={gate} upstream={upstream} calibrating={calibrating} onGateChange={setGate} showBoxes={boxes} showTrails={trails} />
    <div className="vignette" />

    <header className="topbar">
      <Link className="brand" href="/" aria-label="SalmonSight home"><span className="brand-emblem"><Fish strokeWidth={1.6} size={25} /></span><span>SALMON<span className="brand-light">SIGHT</span><i /></span></Link>
      <nav className="top-nav" aria-label="Main navigation"><span className="nav-active">OBSERVATORY</span><button onClick={() => setModal("help")}>THE SCIENCE <ArrowUp size={11} className="diagonal-arrow" /></button></nav>
      <div className="engine-status"><span className="fps"><Activity size={13} /><strong>{(packet?.processing_fps ?? 0).toFixed(1)}</strong> FPS</span><span className={`connection-indicator ${connected ? "connected" : ""}`} title={connected ? "Connected to local analysis engine" : "Analysis engine disconnected"}>{connected ? <Wifi size={15} /> : <WifiOff size={15} />}</span><button className={`icon-button ${settings ? "active" : ""}`} aria-label="Open analysis settings" onClick={() => { if (settings) closeSettings(); else setSettings(true); }}><Settings2 size={18} /></button></div>
    </header>

    <section className="observation-heading">
      <div className="eyebrow"><span className="little-line" /> {mode === "live" ? "A NEW PERSPECTIVE ON PASSAGE" : mode === "trajectories" ? "INDIVIDUAL JOURNEYS. SHARED PATTERNS." : "UNDERSTANDING THE UNSEEN"}</div>
      <h1>{mode === "live" ? <>Every journey,<br /><em>in sight.</em></> : mode === "trajectories" ? <>Follow the<br /><em>whole story.</em></> : <>Beyond<br /><em>the count.</em></>}</h1>
      <p>{mode === "live" ? "See movement. Understand passage." : mode === "trajectories" ? "One fish. A continuous journey through time." : "Discover where movement patterns change."}</p>
    </section>

    <section className="source-panel" aria-label="Current video source">
      <div className="source-kicker"><span className={`status-dot ${running ? "pulsing" : ""}`} /><span>{session?.label || "SIMULATED DATA"}</span><span className="source-channel">CH. 01</span></div>
      <button className="source-name" onClick={() => setModal("source")}><span>{sourceTitle}</span><ChevronDown size={15} /></button>
      <p>{simulated ? "Illustrated habitat · deterministic fish movement" : "Local video · computer vision observation"}</p>
      <button className="source-action" onClick={() => setModal("source")}><Upload size={13} /> ANALYZE YOUR FOOTAGE <ArrowUp size={12} className="diagonal-arrow" /></button>
    </section>

    <div className="frame-coordinate frame-coordinate-left">OBSERVATION WINDOW <span>01 — {simulated ? "SIMULATION" : "VIDEO"}</span></div>
    <button className="flow-label" onClick={() => { setSettings(true); setCalibrating(true); }} title="Calibrate upstream direction"><span>UPSTREAM</span><DirectionIcon size={16} /><i /><span className="flow-caption">FLOW REFERENCE</span></button>

    {mode === "trajectories" && <div className="mode-tools trajectory-filters" role="group" aria-label="Trajectory filters">{FILTERS.map(f => <button key={f} className={filter === f ? "active" : ""} onClick={() => setFilter(f)}>{f}</button>)}</div>}
    {mode === "behavior" && <div className="mode-tools heatmap-switch" role="group" aria-label="Heatmap type"><button className={heatmap === "density" ? "active" : ""} onClick={() => setHeatmap("density")}><Waves size={13} /> Movement density</button><button className={heatmap === "friction" ? "active" : ""} onClick={() => setHeatmap("friction")}><Sparkles size={13} /> Behavior friction</button></div>}

    {mode === "behavior" && hotspot && <div className="hotspot-callout"><div className="panel-kicker"><span className="amber-dot" /> POSSIBLE PASSAGE FRICTION</div><p>{hotspot.reversals > 0 ? `${hotspot.reversals} reversal${hotspot.reversals === 1 ? "" : "s"} observed in the highlighted region.` : "Elevated residence time in the highlighted region."}</p><div><strong>{hotspot.baseline_ratio !== null ? `${hotspot.baseline_ratio.toFixed(1)}×` : `${hotspot.dwell_seconds.toFixed(1)}s`}</strong><span>{hotspot.baseline_ratio !== null ? "typical passage cell dwell" : "longest cell residence"}</span></div><small>A behavioral observation for human review.</small></div>}

    <section className="hud-panel passage-panel" aria-label="Passage statistics">
      <div className="panel-top"><span className="panel-kicker"><Radio size={12} /> PASSAGE</span><span className="tiny-tag">{running ? "TRACKING" : started ? "PAUSED" : "READY"}</span></div>
      <div className="passage-headline"><div><span className="stat-label">Upstream passages</span><div className="big-stat" key={summary.upstream}>{String(summary.upstream).padStart(2, "0")}<ArrowUp size={24} strokeWidth={1.4} /></div></div><div className="downstream-stat"><ArrowDown size={16} /><strong>{String(summary.downstream).padStart(2, "0")}</strong><span>downstream</span></div></div>
      <div className="panel-divider" />
      <Metric label="Active tracks" value={<>{summary.active}<span className={`live-dot ${running ? "pulsing" : ""}`} /></>}><Focus size={13} /></Metric>
      <Metric label="Passage rate" value={<>{Math.round(summary.passage_rate)}<small> / hr</small></>}><Gauge size={13} /></Metric>
      <div className="panel-footnote">{started ? `${summary.tracks_produced} individual tracks observed` : "A new perspective starts with one fish."}<span>↗</span></div>
    </section>

    <section className="hud-panel behavior-panel" aria-label="Behavior statistics">
      <div className="panel-top"><span className="panel-kicker"><GitBranch size={12} /> BEHAVIOR</span><span className="tiny-tag">TRAJECTORY ENGINE</span></div>
      <div className="behavior-highlight"><span>Passage success</span><strong>{summary.success_rate === null ? "—" : Math.round(summary.success_rate)}{summary.success_rate !== null && <small>%</small>}</strong></div>
      <div className="success-bar"><div style={{ width: `${summary.success_rate ?? 0}%` }} /></div>
      <div className="behavior-grid"><div><span className="amber-text"><RotateCcw size={12} /> Reversals</span><strong>{String(summary.reversals).padStart(2, "0")}</strong></div><div><span><Activity size={12} /> Long dwell</span><strong>{String(summary.long_dwell).padStart(2, "0")}</strong></div></div>
      <div className="panel-divider" />
      <Metric label="Successful passages" value={summary.successful} />
      <Metric label="Passage attempts" value={summary.attempts} />
      <div className="panel-footnote">{summary.median_passage_seconds !== null ? `${summary.median_passage_seconds.toFixed(1)}s median passage time` : "Building an understanding, over time."}<span>↗</span></div>
    </section>

    {selectedTrack && <aside className="hud-panel selected-panel" aria-label={`Fish ${selectedTrack.id} details`}><div className="panel-top"><span className="panel-kicker"><Crosshair size={12} /> INDIVIDUAL JOURNEY</span><button className="close-button" aria-label="Close fish details" onClick={() => setSelected(null)}><X size={15} /></button></div><div className="selected-heading"><h2>Fish #{String(selectedTrack.id).padStart(3, "0")}</h2><span className={`track-result ${selectedTrack.status === "REVERSED" ? "amber-text" : ""}`}>{selectedTrack.status}</span></div><Metric label="Direction" value={selectedTrack.direction} /><Metric label="Observed" value={`${selectedTrack.time_observed.toFixed(1)} sec`} /><Metric label="Passage attempts" value={selectedTrack.attempts} /><Metric label="Reversals" value={selectedTrack.reversals} /><Metric label="Speed" value={`${(selectedTrack.velocity * 100).toFixed(1)}% frame / s`} /><p className="selected-note">Full trajectory highlighted in the observation window.</p></aside>}

    <div className={`analysis-control ${started ? "analysis-control-started" : ""}`}>
      {!started && <div className="start-caption"><span /><span>THE STORY IS IN THE MOVEMENT</span><span /></div>}
      <button className={`primary-button ${running ? "pause-button" : ""}`} onClick={() => void toggleAnalysis()} disabled={busy || connecting || calibrating}>
        {busy || connecting ? <LoaderCircle className="spin" size={16} /> : running ? <Pause size={14} fill="currentColor" /> : <Play size={14} fill="currentColor" />}
        {connecting ? "CONNECTING" : busy ? "PLEASE WAIT" : running ? "PAUSE ANALYSIS" : !session ? "RECONNECT ENGINE" : started ? session.completed ? "REPLAY ANALYSIS" : "RESUME ANALYSIS" : "START ANALYSIS"}
        {!running && !busy && <ArrowRight size={17} />}
      </button>
      {!started && <span className="start-note">{simulated ? "Explore the visualization demo. No setup needed." : "Local detection. Individual tracks. Meaningful behavior."}</span>}
    </div>

    {started && <div className="activity-feed" aria-label="Recent passage activity" aria-live="polite">{events.length > 0 ? events.map(event => <button key={event.id} className={`activity-event ${event.type === "REVERSAL" ? "event-amber" : ""}`} onClick={() => setSelected(event.track_id)}>{event.type === "REVERSAL" ? <RotateCcw size={13} /> : event.type === "LONG_DWELL" ? <Activity size={13} /> : <ArrowUp size={13} />}<span>{event.message}</span><time>{formatTime(event.timestamp)}</time></button>) : <div className="activity-empty"><span className="status-dot pulsing" /> Following individual movement. Passage events will appear here.</div>}</div>}

    <div className="bottom-controls"><div className="view-caption">A DIFFERENT WAY OF SEEING</div><div className="view-switch" role="group" aria-label="Observation view">{([{ id: "live", name: "Live", icon: Eye }, { id: "trajectories", name: "Trajectories", icon: GitBranch }, { id: "behavior", name: "Behavior", icon: Layers }] as const).map(view => <button key={view.id} aria-pressed={mode === view.id} className={mode === view.id ? "active" : ""} onClick={() => setMode(view.id)}><view.icon size={15} /><span>{view.name}</span>{mode === view.id && <i />}</button>)}</div></div>

    <footer className="footer"><div className="footer-left"><span className="footer-cross">+</span><span>{simulated ? "SIMULATED DATA · NOT A FIELD MEASUREMENT" : `${session?.detector_state || "LOCAL FISHIAL"} · LOCAL ANALYSIS`}</span></div><div className="footer-center"><span className={running ? "record-dot" : "record-dot paused"} /><span>{formatTime(packet?.timestamp ?? 0)}</span><span className="footer-separator">/</span><span>{session?.duration ? formatTime(session.duration) : "OBSERVATION"}</span></div><div className="footer-right"><button onClick={() => setModal("help")} aria-label="About SalmonSight"><CircleHelp size={14} /></button><button onClick={() => { if (document.fullscreenElement) void document.exitFullscreen(); else void document.documentElement.requestFullscreen().catch(() => setToast("Full screen is unavailable in this browser.")); }} aria-label="Toggle full screen"><Maximize2 size={14} /></button><span>SEE. FOLLOW. UNDERSTAND.</span></div></footer>

    {settings && <aside className="settings-panel hud-panel" aria-label="Analysis settings"><div className="panel-top"><span className="panel-kicker"><SlidersHorizontal size={13} /> OBSERVATION SETTINGS</span><button className="close-button" onClick={closeSettings} aria-label="Close settings"><X size={17} /></button></div><h2>Set your perspective.</h2><p>Every camera sees passage differently. Define the direction and gate for this view.</p><label className="settings-label">UPSTREAM DIRECTION</label><div className="direction-choices">{DIRECTIONS.map(direction => <button aria-label={`Upstream ${direction.name.toLowerCase()}`} title={direction.name} key={direction.name} className={upstream[0] === direction.vector[0] && upstream[1] === direction.vector[1] ? "active" : ""} onClick={() => { setUpstream(direction.vector); setCalibrating(true); }}><direction.icon size={19} /></button>)}</div><button className={`calibrate-button ${calibrating ? "active" : ""}`} onClick={() => setCalibrating(!calibrating)}><Crosshair size={15} />{calibrating ? "Drag the gate’s two endpoints" : "Adjust passage gate"}<span>{calibrating ? "EDITING" : "EDIT"}</span></button><div className="panel-divider" /><label className="toggle-label">Bounding boxes<input type="checkbox" checked={boxes} onChange={e => setBoxes(e.target.checked)} /><span className="toggle" /></label><label className="toggle-label">Trajectory trails<input type="checkbox" checked={trails} onChange={e => setTrails(e.target.checked)} /><span className="toggle" /></label><div className="settings-detector"><span className="settings-label">DETECTION ENGINE</span><strong>{simulated ? "Visualization demo" : "Fishial · local YOLO"}</strong><small>{simulated ? "Synthetic detections → local tracking → behavior" : "General fish detection. No species classification."}</small></div><button className="primary-button save-button" disabled={busy || !session} onClick={() => void saveCalibration()}>{busy ? <LoaderCircle size={14} className="spin" /> : <Check size={14} />} SAVE CALIBRATION</button><small className="reset-note">Saving starts a new observation with reset metrics.</small></aside>}

    {(error || session?.error) && <div className="error-banner" role="alert"><WifiOff size={16} /><span>{error || session?.error}</span><button onClick={() => setError(null)} aria-label="Dismiss notification"><X size={15} /></button></div>}
    {toast && <div className="toast" role="status"><Check size={15} /><span>{toast}</span><button onClick={() => setToast(null)} aria-label="Dismiss message"><X size={14} /></button></div>}

    {modal && <div className="modal-backdrop" onClick={() => setModal(null)}><section className={`modal ${modal === "help" ? "help-modal" : ""}`} role="dialog" aria-modal="true" aria-labelledby="modal-title" onClick={event => event.stopPropagation()}><button className="modal-close icon-button" aria-label="Close dialog" onClick={() => setModal(null)}><X size={20} /></button><span className="eyebrow"><Waves size={15} /> {modal === "source" ? "CHOOSE YOUR PERSPECTIVE" : "THE SCIENCE OF MOVEMENT"}</span><h2 id="modal-title">{modal === "source" ? <>Every stream<br />has a story.</> : <>Detection is<br />just the beginning.</>}</h2>{modal === "source" ? <><p>Open local footage or explore a simulation. SalmonSight follows each fish through the observation window.</p><button className="source-option" disabled={busy} onClick={() => void chooseSource("demo")}><span className="option-icon"><Waves size={23} /></span><span><strong>TRY ISSAQUAH DEMO</strong><small>Local footage & cached detections, when configured.</small></span><ArrowUp className="diagonal-arrow" size={19} /></button><div className={`upload-zone ${dropActive ? "drag-over" : ""}`} onDragOver={event => { event.preventDefault(); setDropActive(true); }} onDragLeave={() => setDropActive(false)} onDrop={event => { event.preventDefault(); setDropActive(false); const file = event.dataTransfer.files[0]; if (file && !busy) void upload(file); }}><Upload size={26} /><strong>Bring your own perspective.</strong><p>Drop your video here, or choose a file.</p><button className="primary-button" disabled={busy} onClick={() => fileInput.current?.click()}>{busy ? <LoaderCircle size={15} className="spin" /> : <Upload size={15} />} ANALYZE YOUR FOOTAGE</button><small>MP4 · MOV · AVI · local processing</small></div><button className="simulation-link" disabled={busy} onClick={() => void chooseSource("visualization")}>Explore the visualization demo <ArrowRight size={14} /></button><div className="source-disclaimer"><span className="status-dot" /> Simulated data is always labeled. No footage is sent to the cloud.</div></> : <><p>SalmonSight transforms fish detections into individual journeys and interpretable observations about passage.</p><div className="science-steps"><div><span>01</span><div><h3>See the fish</h3><p>An existing pretrained Fishial YOLO model detects fish locally. It does not determine species.</p></div></div><div><span>02</span><div><h3>Follow the individual</h3><p>ByteTrack connects detections over time. Persistent identities become movement trails, direction and gate crossings.</p></div></div><div><span>03</span><div><h3>Understand the journey</h3><p>Transparent heuristics identify repeated attempts, meaningful reversals, extended dwell and possible passage friction.</p></div></div></div><div className="science-note">Behavioral observations prioritize human review. They are not biological or engineering diagnoses.</div><p className="model-setup">Local model setup: <code>python scripts/download_model.py</code><br />The visualization demo works without a model or internet connection.</p><button className="primary-button" onClick={() => setModal(null)}>BACK TO THE OBSERVATORY <ArrowRight size={15} /></button></>}</section></div>}
    <input ref={fileInput} className="file-input" type="file" accept="video/mp4,video/quicktime,video/x-msvideo,.mp4,.mov,.avi" onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file); }} />
  </main>;
}
