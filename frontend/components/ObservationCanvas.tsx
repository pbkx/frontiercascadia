"use client";

import { useEffect, useRef } from "react";
import type { Gate, Point, Snapshot, Track, TrackFilter, ViewMode } from "@/lib/types";

interface Props {
  packet: Snapshot | null;
  tracks: Track[];
  mode: ViewMode;
  filter: TrackFilter;
  heatmap: "density" | "friction";
  selected: number | null;
  onSelect: (id: number | null) => void;
  gate: Gate;
  calibrating: boolean;
  onGateChange: (gate: Gate) => void;
  showBoxes: boolean;
  showTrails: boolean;
}

const TRACK = "#80f5c7";
const ALERT = "#ffba72";

function visible(track: Track, filter: TrackFilter, selected: number | null) {
  return filter === "All" ||
    (filter === "Upstream" && track.direction === "upstream") ||
    (filter === "Downstream" && track.direction === "downstream") ||
    (filter === "Reversals" && track.reversals > 0) ||
    (filter === "Long dwell" && track.flags.includes("LONG_DWELL")) ||
    (filter === "Selected" && track.id === selected);
}

export default function ObservationCanvas(props: Props) {
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const heatRef = useRef<HTMLCanvasElement>(null);
  const latest = useRef(props);
  const viewport = useRef({ width: 1, height: 1, sourceW: 1280, sourceH: 720, scale: 1, ox: 0, oy: 0 });
  const dragging = useRef<number | null>(null);

  useEffect(() => { latest.current = props; }, [props]);

  useEffect(() => {
    const overlay = overlayRef.current!;
    const heat = heatRef.current!;
    const ctx = overlay.getContext("2d")!;
    const hm = heat.getContext("2d")!;
    let animation = 0;

    const resize = () => {
      const bounds = overlay.getBoundingClientRect();
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      for (const canvas of [overlay, heat]) {
        canvas.width = Math.round(bounds.width * ratio);
        canvas.height = Math.round(bounds.height * ratio);
      }
      for (const context of [ctx, hm]) context.setTransform(ratio, 0, 0, ratio, 0, 0);
      viewport.current.width = bounds.width;
      viewport.current.height = bounds.height;
    };
    const observer = new ResizeObserver(resize);
    observer.observe(overlay);
    resize();

    const draw = () => {
      const p = latest.current;
      const v = viewport.current;
      const packet = p.packet;
      v.sourceW = packet?.session.width || 1280;
      v.sourceH = packet?.session.height || 720;
      v.scale = Math.max(v.width / v.sourceW, v.height / v.sourceH);
      const shownW = v.sourceW * v.scale;
      const shownH = v.sourceH * v.scale;
      v.ox = (v.width - shownW) / 2;
      v.oy = (v.height - shownH) / 2;
      const point = (normalized: Point): Point => [v.ox + normalized[0] * shownW, v.oy + normalized[1] * shownH];

      ctx.clearRect(0, 0, v.width, v.height);
      hm.clearRect(0, 0, v.width, v.height);

      if (p.mode === "behavior" && packet?.heatmaps) {
        const grid = packet.heatmaps[p.heatmap];
        const maximum = Math.max(0.001, ...grid.flat());
        hm.save();
        hm.globalCompositeOperation = "screen";
        grid.forEach((row, yi) => row.forEach((value, xi) => {
          if (value <= 0) return;
          const [x, y] = point([(xi + .5) / packet.heatmaps.columns, (yi + .5) / packet.heatmaps.rows]);
          const strength = Math.sqrt(value / maximum);
          const radius = shownW / packet.heatmaps.columns * 1.4;
          const gradient = hm.createRadialGradient(x, y, 0, x, y, radius);
          const rgb = p.heatmap === "density" ? "54,236,185" : "255,138,70";
          gradient.addColorStop(0, `rgba(${rgb},${strength * .55})`);
          gradient.addColorStop(.45, `rgba(${rgb},${strength * .2})`);
          gradient.addColorStop(1, `rgba(${rgb},0)`);
          hm.fillStyle = gradient;
          hm.fillRect(x - radius, y - radius, radius * 2, radius * 2);
        }));
        hm.restore();
      }

      if (packet && packet.session.source_type !== "simulated") {
        const [a, b] = p.gate.map(point);
        ctx.save();
        ctx.strokeStyle = p.calibrating ? "rgba(255,255,255,.95)" : "rgba(255,255,255,.48)";
        ctx.lineWidth = p.calibrating ? 2 : 1;
        ctx.setLineDash([6, 6]);
        ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = "rgba(5,12,15,.72)";
        const gx = (a[0] + b[0]) / 2;
        const gy = (a[1] + b[1]) / 2;
        ctx.fillRect(gx - 48, gy - 10, 96, 20);
        ctx.fillStyle = "rgba(255,255,255,.82)";
        ctx.font = "10px ui-monospace, monospace";
        ctx.textAlign = "center";
        ctx.fillText(p.calibrating ? "DRAG ENDPOINTS" : "COUNTING LINE", gx, gy + 4);
        for (const endpoint of [a, b]) {
          ctx.fillStyle = p.calibrating ? "white" : "rgba(255,255,255,.7)";
          ctx.beginPath(); ctx.arc(endpoint[0], endpoint[1], p.calibrating ? 7 : 3, 0, Math.PI * 2); ctx.fill();
        }
        ctx.restore();
      }

      for (const track of p.tracks) {
        const active = track.active ?? ((packet?.timestamp || 0) - track.last_seen < 1.5);
        if (p.mode === "live" && !active && track.id !== p.selected) continue;
        const matches = p.mode === "live" || visible(track, p.filter, p.selected);
        const selected = track.id === p.selected;
        const alpha = matches ? (p.selected !== null && !selected ? .28 : 1) : .06;
        const color = track.reversals > 0 || track.flags.includes("LONG_DWELL") ? ALERT : TRACK;
        const trail = track.trajectory || [];
        ctx.save();
        ctx.globalAlpha = alpha;

        if (p.showTrails || p.mode !== "live" || selected) {
          const points = p.mode === "live" && !selected ? trail.slice(-30) : trail;
          for (let index = 1; index < points.length; index++) {
            ctx.globalAlpha = alpha * (.18 + index / points.length * .72);
            ctx.strokeStyle = color;
            ctx.lineWidth = selected ? 2.5 : p.mode === "trajectories" ? 1.8 : 1.2;
            ctx.beginPath();
            ctx.moveTo(...point([points[index - 1][0], points[index - 1][1]]));
            ctx.lineTo(...point([points[index][0], points[index][1]]));
            ctx.stroke();
          }
        }

        ctx.globalAlpha = alpha;
        if ((p.showBoxes && active) || selected) {
          const [x1, y1] = point([track.bbox[0], track.bbox[1]]);
          const [x2, y2] = point([track.bbox[2], track.bbox[3]]);
          const labelY = y1 < 100 ? y1 + 2 : y1 - 25;
          ctx.strokeStyle = color;
          ctx.lineWidth = selected ? 2.2 : 1.5;
          ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
          ctx.fillStyle = "rgba(3,10,13,.78)";
          ctx.fillRect(x1, labelY, 142, 24);
          ctx.font = "600 11px ui-monospace, monospace";
          ctx.textAlign = "left";
          ctx.fillStyle = "white";
          ctx.fillText(`FISH #${track.id}`, x1 + 7, labelY + 16);
          ctx.textAlign = "right";
          ctx.fillStyle = color;
          ctx.fillText(`${Math.round(track.confidence * 100)}%`, x1 + 135, labelY + 16);

          if (track.direction !== "uncertain" && track.smoothed_velocity) {
            const magnitude = Math.hypot(...track.smoothed_velocity) || 1;
            const dx = track.smoothed_velocity[0] / magnitude;
            const dy = track.smoothed_velocity[1] / magnitude;
            const startX = (x1 + x2) / 2 - dx * 13;
            const startY = y2 + 14;
            const endX = startX + dx * 38;
            const endY = startY + dy * 38;
            ctx.strokeStyle = color; ctx.lineWidth = 1.5;
            ctx.beginPath(); ctx.moveTo(startX, startY); ctx.lineTo(endX, endY);
            ctx.lineTo(endX - dx * 7 - dy * 4, endY - dy * 7 + dx * 4);
            ctx.moveTo(endX, endY); ctx.lineTo(endX - dx * 7 + dy * 4, endY - dy * 7 - dx * 4); ctx.stroke();
            ctx.font = "10px ui-monospace, monospace";
            ctx.textAlign = "center";
            ctx.fillText(track.direction, (x1 + x2) / 2, y2 + 36);
          }
        }

        if (p.mode !== "live" && matches) {
          for (const reversal of track.reversal_locations || []) {
            const [x, y] = point(reversal);
            ctx.strokeStyle = ALERT; ctx.lineWidth = 1.5;
            ctx.beginPath(); ctx.arc(x, y, 7, 0, Math.PI * 2); ctx.stroke();
          }
        }
        ctx.restore();
      }
      animation = requestAnimationFrame(draw);
    };
    animation = requestAnimationFrame(draw);
    return () => { cancelAnimationFrame(animation); observer.disconnect(); };
  }, []);

  const normalize = (event: React.PointerEvent<HTMLCanvasElement>): Point => {
    const v = viewport.current;
    const bounds = event.currentTarget.getBoundingClientRect();
    return [
      Math.min(1, Math.max(0, (event.clientX - bounds.left - v.ox) / (v.sourceW * v.scale))),
      Math.min(1, Math.max(0, (event.clientY - bounds.top - v.oy) / (v.sourceH * v.scale))),
    ];
  };

  return <>
    <canvas ref={heatRef} className="heat-canvas" aria-hidden="true" />
    <canvas
      ref={overlayRef}
      className={`cv-canvas ${props.calibrating ? "calibrating" : ""}`}
      aria-label="Fish tracking overlay. Select a fish to inspect its track."
      onPointerDown={event => {
        const position = normalize(event);
        if (props.calibrating) {
          const distances = props.gate.map(endpoint => Math.hypot(
            (endpoint[0] - position[0]) * viewport.current.sourceW * viewport.current.scale,
            (endpoint[1] - position[1]) * viewport.current.sourceH * viewport.current.scale,
          ));
          const nearest = distances[0] < distances[1] ? 0 : 1;
          if (distances[nearest] < 40) {
            dragging.current = nearest;
            event.currentTarget.setPointerCapture(event.pointerId);
          }
          return;
        }
        const track = [...props.tracks].reverse().find(item => position[0] >= item.bbox[0] && position[0] <= item.bbox[2] && position[1] >= item.bbox[1] && position[1] <= item.bbox[3]);
        props.onSelect(track?.id ?? null);
      }}
      onPointerMove={event => {
        if (dragging.current === null) return;
        const next: Gate = [[...props.gate[0]], [...props.gate[1]]];
        next[dragging.current] = normalize(event);
        props.onGateChange(next);
      }}
      onPointerUp={() => { dragging.current = null; }}
      onPointerCancel={() => { dragging.current = null; }}
    />
  </>;
}
