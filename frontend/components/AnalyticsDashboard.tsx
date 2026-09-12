"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronDown, ChevronUp, Minus, X } from "lucide-react";
import { backendUrl } from "@/lib/api";

type Range = "5m" | "15m" | "1h" | "all" | "full";
type SeriesKey = "fish_observed" | "upstream_crossings" | "downstream_crossings";
type SortKey = "id" | "direction" | "observed_time" | "relative_speed" | "reversals";
type View = "activity" | "direction" | "events" | "observed" | "speed" | "comparison" | "scatter" | "tracks";
interface Bucket { start: number; end: number; fish_observed?: number; upstream_crossings?: number; downstream_crossings?: number; reversals?: number; long_dwell?: number }
interface Distribution { label: string; min: number; max: number | null; count: number }
interface TrackRow { id: number; display_id?: number; direction: "upstream" | "downstream" | "uncertain"; observed_time: number; relative_speed: number; distance: number; reversals: number; crossed: boolean; first_seen: number }
interface Group { count: number; median_observed_time: number | null; median_relative_speed: number | null; median_distance: number | null; upstream_crossing_rate: number | null }
interface AnalyticsData {
  session_id: string; source_type: string; source_name: string; range: Range;
  observation: { start: number; end: number; seconds: number; bucket_seconds: number };
  summary: { fish_tracked: number; upstream_percent: number | null; downstream_percent: number | null; reversal_rate: number | null; median_observed_time: number | null; median_relative_speed: number | null };
  findings: string[]; activity: Bucket[]; behavior_events: Bucket[];
  direction: { name: "upstream" | "downstream" | "uncertain"; count: number; percent: number }[];
  observed_time_distribution: Distribution[]; observed_time_stats: { median: number | null; p90: number | null; longest: number | null };
  speed_distribution: Distribution[]; speed_stats: { median: number | null; p90: number | null };
  normal_vs_reversal: { normal: Group; reversal: Group };
  scatter: { id: number; display_id?: number; speed: number; observed_time: number; reversal: boolean }[]; tracks: TrackRow[];
}

const SERIES: { key: SeriesKey; label: string; color: string }[] = [
  { key: "fish_observed", label: "Fish observed", color: "#80f5c7" },
  { key: "upstream_crossings", label: "Upstream", color: "#d8fff1" },
  { key: "downstream_crossings", label: "Downstream", color: "#ffba72" },
];

const VIEWS: { key: View; label: string }[] = [
  { key: "activity", label: "Activity" }, { key: "direction", label: "Direction" },
  { key: "events", label: "Behavior events" }, { key: "observed", label: "Time observed" },
  { key: "speed", label: "Speed" }, { key: "comparison", label: "Track comparison" },
  { key: "scatter", label: "Speed vs time" }, { key: "tracks", label: "Tracks" },
];

function duration(seconds: number | null, compact = false) {
  if (seconds === null) return "—";
  if (seconds >= 3600) return `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m`;
  if (seconds >= 60) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return compact ? `${seconds.toFixed(1)}s` : `${Math.round(seconds)}s`;
}

function number(value: number | null, digits = 1) { return value === null ? "—" : value.toFixed(digits); }
function Empty({ text }: { text: string }) { return <div className="analytics-empty">{text}</div>; }

function LineChart({ data, series }: { data: Bucket[]; series: { key: keyof Bucket; label: string; color: string }[] }) {
  if (!data.length || !series.some(item => data.some(bucket => Number(bucket[item.key] || 0) > 0))) return <Empty text="No activity recorded in this period." />;
  const width = 900, height = 280, left = 38, right = 16, top = 18, bottom = 35;
  const max = Math.max(1, ...data.flatMap(bucket => series.map(item => Number(bucket[item.key] || 0))));
  const x = (index: number) => data.length === 1 ? (left + width - right) / 2 : left + index / (data.length - 1) * (width - left - right);
  const y = (value: number) => top + (1 - value / max) * (height - top - bottom);
  const primaryPoints = data.map((bucket, index) => `${x(index)},${y(Number(bucket[series[0].key] || 0))}`).join(" ");
  return <svg className="analytics-chart line-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={series.map(item => item.label).join(", ") + " over time"}>
    {[0, .5, 1].map(portion => <g key={portion}><line x1={left} x2={width - right} y1={y(max * portion)} y2={y(max * portion)} /><text x={left - 9} y={y(max * portion) + 4}>{Math.round(max * portion)}</text></g>)}
    {series.length && data.length > 1 && <polygon className="chart-area" points={`${x(0)},${y(0)} ${primaryPoints} ${x(data.length - 1)},${y(0)}`} fill={series[0].color} />}
    {series.map(item => <g key={String(item.key)}><polyline points={data.map((bucket, index) => `${x(index)},${y(Number(bucket[item.key] || 0))}`).join(" ")} fill="none" stroke={item.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      {data.map((bucket, index) => <g key={index}><circle className="chart-hit" cx={x(index)} cy={y(Number(bucket[item.key] || 0))} r="8"><title>{`${item.label}: ${bucket[item.key] || 0} · ${duration(bucket.start)}`}</title></circle>{(data.length <= 14 || index === data.length - 1) && <circle className="chart-marker" cx={x(index)} cy={y(Number(bucket[item.key] || 0))} r="2.5" fill={item.color} />}</g>)}</g>)}
    <text x={left} y={height - 8}>{duration(data[0].start)}</text><text textAnchor="end" x={width - right} y={height - 8}>{duration(data[data.length - 1].end)}</text>
  </svg>;
}

function Histogram({ data, accent = "mint", empty }: { data: Distribution[]; accent?: "mint" | "amber"; empty: string }) {
  if (!data.length || !data.some(item => item.count)) return <Empty text={empty} />;
  const max = Math.max(1, ...data.map(item => item.count));
  return <div className={`histogram ${accent}`}>{data.map(item => <div className="histogram-bin" key={item.label}>
    <div className="histogram-bar" style={{ height: item.count ? `${Math.max(5, item.count / max * 100)}%` : 0 }}><span>{item.count}</span><title>{`${item.count} tracks · ${item.label}`}</title></div><small>{item.label}</small>
  </div>)}</div>;
}

function StatStrip({ values }: { values: { label: string; value: string }[] }) {
  return <div className="stat-strip">{values.map(item => <div key={item.label}><span>{item.label}</span><strong>{item.value}</strong></div>)}</div>;
}

function Scatter({ points }: { points: AnalyticsData["scatter"] }) {
  if (points.length < 10) return <Empty text="At least 10 tracks with usable speed data are needed for this comparison." />;
  const width = 900, height = 310, left = 54, right = 18, top = 18, bottom = 48;
  const maxX = Math.max(...points.map(point => point.speed), .01), maxY = Math.max(...points.map(point => point.observed_time), 1);
  return <svg className="analytics-chart scatter-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Relative speed versus time observed by track">
    {[0, .5, 1].map(portion => <g key={portion}><line x1={left} x2={width - right} y1={top + portion * (height - top - bottom)} y2={top + portion * (height - top - bottom)} /><text x={left - 9} y={top + portion * (height - top - bottom) + 4}>{Math.round(maxY * (1 - portion))}</text></g>)}
    {points.map(point => <circle key={point.id} cx={left + point.speed / maxX * (width - left - right)} cy={top + (1 - point.observed_time / maxY) * (height - top - bottom)} r="5" className={point.reversal ? "reversal-point" : "normal-point"}><title>{`Fish #${point.display_id ?? point.id}: ${point.speed.toFixed(3)} widths/s, ${point.observed_time.toFixed(1)}s observed`}</title></circle>)}
    <text x={left} y={height - 25}>0</text><text x={width - right} y={height - 25} textAnchor="end">{maxX.toFixed(3)}</text><text x={width / 2} y={height - 8} textAnchor="middle">Relative speed (frame widths / second)</text><text transform={`translate(14 ${height / 2}) rotate(-90)`} textAnchor="middle">Time observed (seconds)</text>
  </svg>;
}

export default function AnalyticsDashboard({ sessionId, onClose }: { sessionId: string | null; onClose: () => void }) {
  const [selectedRange, setSelectedRange] = useState<Range>("all");
  const [activeView, setActiveView] = useState<View>("activity");
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [series, setSeries] = useState<Set<SeriesKey>>(new Set(["fish_observed"]));
  const [sort, setSort] = useState<SortKey>("observed_time");
  const [descending, setDescending] = useState(true);

  const load = useCallback(async () => {
    if (!sessionId) { setLoading(false); return; }
    try {
      const response = await fetch(`${backendUrl()}/api/sessions/${sessionId}/analytics?range=${selectedRange}`, { signal: AbortSignal.timeout(10000) });
      if (!response.ok) throw new Error(response.status === 404 ? "This observation session is no longer available." : "Analytics could not be loaded.");
      setData(await response.json()); setError(null);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Analytics could not be loaded."); }
    finally { setLoading(false); }
  }, [selectedRange, sessionId]);

  useEffect(() => { setLoading(true); void load(); const timer = setInterval(() => void load(), 5000); return () => clearInterval(timer); }, [load]);
  useEffect(() => { const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); }; window.addEventListener("keydown", close); return () => window.removeEventListener("keydown", close); }, [onClose]);

  const sortedTracks = useMemo(() => [...(data?.tracks || [])].sort((a, b) => {
    const av = a[sort], bv = b[sort];
    const comparison = typeof av === "string" ? av.localeCompare(String(bv)) : Number(av) - Number(bv);
    return descending ? -comparison : comparison;
  }), [data?.tracks, descending, sort]);
  const changeSort = (key: SortKey) => { if (sort === key) setDescending(value => !value); else { setSort(key); setDescending(true); } };
  const ranges: { value: Range; label: string }[] = [{ value: "5m", label: "5 MIN" }, { value: "15m", label: "15 MIN" }, { value: "1h", label: "1 HR" }, { value: data?.source_type === "upload" ? "full" : "all", label: data?.source_type === "upload" ? "FULL VIDEO" : "ALL" }];

  const renderView = () => {
    if (!data) return null;
    if (activeView === "activity") return <><div className="workspace-heading"><div><h3>Fish Activity</h3><p>Unique tracks and crossing events per {duration(data.observation.bucket_seconds)}</p></div><div className="series-toggles">{SERIES.map(item => <button key={item.key} className={series.has(item.key) ? "active" : ""} onClick={() => setSeries(current => { const next = new Set(current); if (item.key === "fish_observed" || !next.has(item.key)) next.add(item.key); else next.delete(item.key); return next; })}><i style={{ background: item.color }} />{item.label}</button>)}</div></div><LineChart data={data.activity} series={SERIES.filter(item => series.has(item.key))} /></>;
    if (activeView === "direction") return <><div className="workspace-heading"><div><h3>Movement Direction</h3><p>Final direction of each unique tracked fish</p></div></div>{data.summary.fish_tracked ? <div className="direction-bars">{data.direction.map(item => <div key={item.name}><span>{item.name}</span><div><i style={{ width: `${item.percent}%` }} /></div><strong>{item.percent.toFixed(1)}%</strong><small>{item.count} fish</small><title>{`${item.count} tracks (${item.percent.toFixed(1)}%)`}</title></div>)}</div> : <Empty text="No directional tracks in this period." />}</>;
    if (activeView === "events") return <><div className="workspace-heading"><div><h3>Behavior Events</h3><p>When unusual movement occurred</p></div></div><LineChart data={data.behavior_events} series={[{ key: "reversals", label: "Reversals", color: "#ffba72" }, { key: "long_dwell", label: "Long dwell", color: "#ffe0b8" }]} /></>;
    if (activeView === "observed") return <><div className="workspace-heading"><div><h3>Time Observed</h3><p>Distribution of unique track durations</p></div><StatStrip values={[{ label: "Median", value: duration(data.observed_time_stats.median, true) }, { label: "90th percentile", value: duration(data.observed_time_stats.p90, true) }, { label: "Longest", value: duration(data.observed_time_stats.longest, true) }]} /></div><Histogram data={data.observed_time_distribution} empty="Collecting enough track data…" /></>;
    if (activeView === "speed") return <><div className="workspace-heading"><div><h3>Movement Speed</h3><p>Relative movement · frame widths per second</p></div><StatStrip values={[{ label: "Median · widths/s", value: number(data.speed_stats.median, 3) }, { label: "90th percentile · widths/s", value: number(data.speed_stats.p90, 3) }]} /></div><Histogram data={data.speed_distribution} accent="amber" empty="No usable speed data in this period." /></>;
    if (activeView === "comparison") return <><div className="workspace-heading"><div><h3>Normal vs Reversal Tracks</h3><p>Tracks with zero reversals compared with one or more</p></div></div>{!data.normal_vs_reversal.normal.count || !data.normal_vs_reversal.reversal.count ? <Empty text="Both normal and reversal tracks are needed for comparison." /> : <div className="comparison-table" role="table"><div role="row"><span /><strong>Normal <small>{data.normal_vs_reversal.normal.count} tracks</small></strong><strong>Reversal <small>{data.normal_vs_reversal.reversal.count} tracks</small></strong></div>{[
      ["Median observed", duration(data.normal_vs_reversal.normal.median_observed_time, true), duration(data.normal_vs_reversal.reversal.median_observed_time, true)], ["Median speed (widths/s)", number(data.normal_vs_reversal.normal.median_relative_speed, 3), number(data.normal_vs_reversal.reversal.median_relative_speed, 3)], ["Median distance (widths)", number(data.normal_vs_reversal.normal.median_distance, 3), number(data.normal_vs_reversal.reversal.median_distance, 3)], ["Upstream crossing", data.normal_vs_reversal.normal.upstream_crossing_rate === null ? "—" : `${data.normal_vs_reversal.normal.upstream_crossing_rate}%`, data.normal_vs_reversal.reversal.upstream_crossing_rate === null ? "—" : `${data.normal_vs_reversal.reversal.upstream_crossing_rate}%`],
    ].map(row => <div role="row" key={row[0]}><span>{row[0]}</span><b>{row[1]}</b><b>{row[2]}</b></div>)}</div>}</>;
    if (activeView === "scatter") return <><div className="workspace-heading"><div><h3>Speed vs Time Observed</h3><p>Each point represents one tracked fish</p></div><div className="scatter-legend"><span><i className="normal-point" />Normal</span><span><i className="reversal-point" />Reversal</span></div></div><Scatter points={data.scatter} /></>;
    return <><div className="workspace-heading"><div><h3>Tracks</h3><p>Unique individuals in the selected observation period</p></div></div>{sortedTracks.length ? <div className="table-scroll"><table><thead><tr>{[["Track", "id"], ["Direction", "direction"], ["Observed", "observed_time"], ["Speed (widths/s)", "relative_speed"], ["Distance (widths)", null], ["Reversals", "reversals"], ["Crossed", null]].map(([label, key]) => <th key={label}>{key ? <button onClick={() => changeSort(key as SortKey)}>{label}{sort === key ? descending ? <ChevronDown size={13} /> : <ChevronUp size={13} /> : null}</button> : label}</th>)}</tr></thead><tbody>{sortedTracks.map(track => <tr key={track.id}><td>#{track.display_id ?? track.id}</td><td><span className={`direction-label ${track.direction}`}>{track.direction === "upstream" ? <ArrowUp size={13} /> : track.direction === "downstream" ? <ArrowDown size={13} /> : <Minus size={13} />}{track.direction}</span></td><td>{duration(track.observed_time, true)}</td><td>{track.relative_speed.toFixed(3)}</td><td>{track.distance.toFixed(3)}</td><td>{track.reversals}</td><td>{track.crossed ? "Yes" : "No"}</td></tr>)}</tbody></table></div> : <Empty text="No tracks were observed in this period." />}</>;
  };

  return <div className="analytics-backdrop" onPointerDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="analytics-modal" role="dialog" aria-modal="true" aria-label="Analytics">
      <div className="analytics-modal-body">
        <div className="analytics-toolbar"><div className="range-switch" role="group" aria-label="Analytics time range">{ranges.map(item => <button key={item.value} className={selectedRange === item.value || selectedRange === "all" && item.value === "full" ? "active" : ""} onClick={() => setSelectedRange(item.value)}>{item.label}</button>)}</div><button className="analytics-close" aria-label="Close analytics" onClick={onClose}><X size={17} /></button></div>
        {loading && !data ? <Empty text="Collecting observation data…" /> : error && !data ? <Empty text={error} /> : !data ? <Empty text="Start an observation to view collected behavior data." /> : <>
          {error && <div className="analytics-warning">{error}</div>}
          <section className="summary-grid" aria-label="Analytics summary">{[
            ["Fish tracked", String(data.summary.fish_tracked)], ["Upstream", data.summary.upstream_percent === null ? "—" : `${data.summary.upstream_percent.toFixed(1)}%`], ["Downstream", data.summary.downstream_percent === null ? "—" : `${data.summary.downstream_percent.toFixed(1)}%`], ["Reversal rate", data.summary.reversal_rate === null ? "—" : `${data.summary.reversal_rate.toFixed(1)}%`], ["Median observed", duration(data.summary.median_observed_time, true)], ["Median speed · widths/s", number(data.summary.median_relative_speed, 3)],
          ].map(([label, value]) => <div className="summary-card" key={label}><span>{label}</span><strong>{value}</strong></div>)}</section>
          <nav className="analytics-view-switch" aria-label="Analytics views">{VIEWS.map(item => <button key={item.key} aria-pressed={activeView === item.key} className={activeView === item.key ? "active" : ""} onClick={() => setActiveView(item.key)}>{item.label}</button>)}</nav>
          <div className="analytics-dashboard-grid">
            <section className="analytics-workspace" aria-live="polite">{renderView()}</section>
            <aside className="findings-card"><div><span>Summary</span><h3>Key Findings</h3></div>{data.findings.length ? <ol>{data.findings.map((finding, index) => <li key={finding}><span>{String(index + 1).padStart(2, "0")}</span><p>{finding}</p></li>)}</ol> : <Empty text="Collecting enough track data for supported findings…" />}</aside>
          </div>
        </>}
      </div>
    </section>
  </div>;
}
