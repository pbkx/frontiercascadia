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
  upstream: Point;
  calibrating: boolean;
  onGateChange: (gate: Gate) => void;
  showBoxes: boolean;
  showTrails: boolean;
}

const MINT = "#c7eed1";
const AMBER = "#f0b981";
function rng(seed: number) {
  return () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
}
function isVisible(track: Track, filter: TrackFilter, selected: number | null) {
  return filter === "All" || (filter === "Successful" && track.status === "PASSED") ||
    (filter === "Reversals" && track.reversals > 0) || (filter === "Long dwell" && track.flags.includes("LONG_DWELL")) ||
    (filter === "Selected" && track.id === selected);
}

function buildHabitat(width: number, height: number) {
  const canvas = document.createElement("canvas");
  canvas.width = width; canvas.height = height;
  const ctx = canvas.getContext("2d")!;
  const random = rng(194184);
  const water = ctx.createLinearGradient(0, 0, width * 0.8, height);
  water.addColorStop(0, "#7c8764"); water.addColorStop(0.3, "#546a4b"); water.addColorStop(0.65, "#344b39"); water.addColorStop(1, "#132d28");
  ctx.fillStyle = water; ctx.fillRect(0, 0, width, height);
  // Light entering through the rippled surface.
  ctx.save(); ctx.globalCompositeOperation = "screen";
  for (let n = 0; n < 9; n++) {
    const x = width * (0.1 + random() * 0.85);
    const ray = ctx.createLinearGradient(x, 0, x - width * 0.28, height);
    ray.addColorStop(0, "rgba(229,226,174,0.12)"); ray.addColorStop(0.75, "rgba(201,226,165,0.018)"); ray.addColorStop(1, "rgba(201,226,165,0)");
    ctx.fillStyle = ray; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x + width * 0.05, 0); ctx.lineTo(x - width * 0.12, height); ctx.lineTo(x - width * 0.4, height); ctx.closePath(); ctx.fill();
  }
  ctx.restore();
  // A riverbed with individually shaded stones, kept soft behind the tracking layer.
  const floor = ctx.createLinearGradient(0, height * 0.59, 0, height);
  floor.addColorStop(0, "rgba(31,49,34,0)"); floor.addColorStop(0.42, "rgba(55,60,40,0.6)"); floor.addColorStop(1, "#444534");
  ctx.fillStyle = floor; ctx.fillRect(0, height * 0.55, width, height * 0.45);
  for (let n = 0; n < 380; n++) {
    const y = height * (0.71 + random() * 0.32);
    const x = random() * width;
    const depth = (y / height - 0.68) * 3;
    const rx = (5 + random() * 35) * Math.max(0.12, depth), ry = rx * (0.3 + random() * 0.4);
    const light = 30 + Math.floor(random() * 42);
    ctx.save(); ctx.translate(x, y); ctx.rotate(random() * 2);
    const stone = ctx.createRadialGradient(-rx * 0.3, -ry * 0.5, 0, 0, 0, rx);
    stone.addColorStop(0, `rgb(${light + 9},${light + 12},${light - 1})`); stone.addColorStop(0.65, `rgb(${light - 5},${light},${light - 8})`); stone.addColorStop(1, "#26392b");
    ctx.fillStyle = stone; ctx.beginPath(); ctx.ellipse(0, 0, rx, ry, 0, 0, Math.PI * 2); ctx.fill(); ctx.restore();
  }
  // Boulder edges rise into the scene; subdued irregular shapes avoid a flat background.
  for (let side = 0; side < 2; side++) {
    for (let n = 0; n < 7; n++) {
      const x = side === 0 ? -width * 0.07 + n * width * 0.034 : width * 1.055 - n * width * 0.028;
      const y = height * (0.69 + n * 0.046);
      const rx = width * (0.1 + random() * 0.07), ry = height * (0.07 + random() * 0.06);
      const rock = ctx.createRadialGradient(x - rx * 0.2, y - ry * 0.6, 2, x, y, rx);
      rock.addColorStop(0, "#697057"); rock.addColorStop(0.4, "#4a5640"); rock.addColorStop(1, "#1d3027");
      ctx.fillStyle = rock; ctx.beginPath();
      for (let p = 0; p <= 14; p++) {
        const a = p / 14 * Math.PI * 2, noise = 0.8 + random() * 0.3;
        const px = x + Math.cos(a) * rx * noise, py = y + Math.sin(a) * ry * noise;
        if (p === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      }
      ctx.closePath(); ctx.fill();
    }
  }
  // Fine optical grain is generated once, keeping animation inexpensive.
  const grain = document.createElement("canvas"); grain.width = 400; grain.height = 250;
  const g = grain.getContext("2d")!, pixels = g.createImageData(400, 250);
  for (let p = 0; p < pixels.data.length; p += 4) {
    const value = random() > 0.5 ? 220 : 10;
    pixels.data[p] = value; pixels.data[p + 1] = value; pixels.data[p + 2] = value; pixels.data[p + 3] = random() * 18;
  }
  g.putImageData(pixels, 0, 0); ctx.drawImage(grain, 0, 0, width, height);
  return canvas;
}

function fish(ctx: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, angle: number, time: number, seed: number) {
  ctx.save(); ctx.translate(x, y); ctx.rotate(angle); ctx.scale(width, height);
  const sway = Math.sin(time * 4 + seed) * 0.08;
  // Faint shadow, salmon's forked tail and dorsal fins.
  ctx.fillStyle = "rgba(10,29,23,.18)"; ctx.beginPath(); ctx.ellipse(0, 0.28, 0.41, 0.24, 0, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#465345"; ctx.beginPath(); ctx.moveTo(-0.31, 0); ctx.lineTo(-0.51, -0.41 + sway); ctx.quadraticCurveTo(-0.48, -0.05, -0.44, sway); ctx.lineTo(-0.51, 0.39 + sway); ctx.lineTo(-0.3, 0.08); ctx.closePath(); ctx.fill();
  ctx.fillStyle = "#59644e"; ctx.beginPath(); ctx.moveTo(-0.09, -0.19); ctx.lineTo(-0.1, -0.49); ctx.quadraticCurveTo(0.01, -0.54, 0.15, -0.19); ctx.fill();
  ctx.fillStyle = "#66735b"; ctx.beginPath(); ctx.moveTo(-0.08, 0.18); ctx.lineTo(-0.16, 0.43); ctx.lineTo(0.1, 0.2); ctx.fill();
  const body = ctx.createLinearGradient(0, -0.28, 0, 0.31);
  body.addColorStop(0, "#364b3e"); body.addColorStop(0.26, "#7f9073"); body.addColorStop(0.5, "#b0b798"); body.addColorStop(0.72, "#b2b699"); body.addColorStop(1, "#657762");
  ctx.fillStyle = body;
  ctx.beginPath(); ctx.moveTo(-0.37, 0); ctx.bezierCurveTo(-0.16, -0.26, 0.18, -0.32, 0.37, -0.14); ctx.quadraticCurveTo(0.49, -0.07, 0.5, 0.025); ctx.quadraticCurveTo(0.42, 0.15, 0.28, 0.18); ctx.bezierCurveTo(0.06, 0.3, -0.16, 0.2, -0.37, 0.065); ctx.closePath(); ctx.fill();
  // Lateral stripe, scales, gill and pectoral fin.
  ctx.strokeStyle = "rgba(135,112,97,.5)"; ctx.lineWidth = 0.06; ctx.beginPath(); ctx.moveTo(-0.29, 0.025); ctx.quadraticCurveTo(0.02, -0.004, 0.3, 0.025); ctx.stroke();
  const random = rng(seed * 114 + 62);
  for (let i = 0; i < 40; i++) {
    const sx = random() * 0.58 - 0.28, sy = random() * 0.2 - 0.18;
    ctx.fillStyle = "rgba(24,45,34,.39)"; ctx.beginPath(); ctx.ellipse(sx, sy, 0.003 + random() * 0.005, 0.01 + random() * 0.008, -0.3, 0, Math.PI * 2); ctx.fill();
  }
  ctx.strokeStyle = "rgba(37,57,41,.6)"; ctx.lineWidth = 0.008; ctx.beginPath(); ctx.moveTo(0.26, -0.14); ctx.quadraticCurveTo(0.35, 0.045, 0.23, 0.16); ctx.stroke();
  ctx.fillStyle = "#72816a"; ctx.beginPath(); ctx.moveTo(0.19, 0.06); ctx.lineTo(0.04, 0.35); ctx.lineTo(0.24, 0.19); ctx.fill();
  ctx.fillStyle = "#b9be9d"; ctx.beginPath(); ctx.ellipse(0.383, -0.057, 0.023, 0.037, 0, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#162a20"; ctx.beginPath(); ctx.ellipse(0.39, -0.058, 0.012, 0.024, 0, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "rgba(240,239,198,.7)"; ctx.beginPath(); ctx.ellipse(0.394, -0.067, 0.004, 0.008, 0, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = "#4d5f48"; ctx.lineWidth = 0.007; ctx.beginPath(); ctx.moveTo(0.42, 0.04); ctx.lineTo(0.488, 0.021); ctx.stroke();
  ctx.restore();
}

export default function ObservationCanvas(props: Props) {
  const sceneRef = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const heatRef = useRef<HTMLCanvasElement>(null);
  const latest = useRef(props);
  const viewport = useRef({ width: 1, height: 1, scale: 1, ox: 0, oy: 0, sourceW: 1280, sourceH: 720 });
  const dragging = useRef<number | null>(null);
  useEffect(() => { latest.current = props; }, [props]);

  useEffect(() => {
    const scene = sceneRef.current!, overlay = overlayRef.current!, heat = heatRef.current!;
    const ctx = scene.getContext("2d")!, cv = overlay.getContext("2d")!, hm = heat.getContext("2d")!;
    const backdrop = buildHabitat(1600, 900);
    let animation = 0, lastEvent: string | number | undefined, gateFlash = 0;
    let lastHeatFrame = -1, lastHeatType = "", lastHeatMode = "";
    const resize = () => {
      const box = scene.getBoundingClientRect();
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      for (const canvas of [scene, overlay, heat]) { canvas.width = box.width * ratio; canvas.height = box.height * ratio; }
      for (const context of [ctx, cv, hm]) context.setTransform(ratio, 0, 0, ratio, 0, 0);
      viewport.current.width = box.width; viewport.current.height = box.height; lastHeatFrame = -1;
    };
    const observer = new ResizeObserver(resize); observer.observe(scene); resize();
    const draw = (ms: number) => {
      const p = latest.current, v = viewport.current, packet = p.packet;
      const { width: w, height: h } = v;
      const time = ms / 1000;
      v.sourceW = packet?.session.width || 1280; v.sourceH = packet?.session.height || 720;
      v.scale = Math.max(w / v.sourceW, h / v.sourceH);
      const sw = v.sourceW * v.scale, sh = v.sourceH * v.scale;
      v.ox = (w - sw) / 2; v.oy = (h - sh) / 2;
      const pos = (pt: Point): Point => [v.ox + pt[0] * sw, v.oy + pt[1] * sh];
      const simulated = !packet || packet.session.mode === "VISUALIZATION_DEMO";
      ctx.clearRect(0, 0, w, h); cv.clearRect(0, 0, w, h);
      if (simulated) {
        ctx.drawImage(backdrop, 0, 0, w, h);
        ctx.save();
        ctx.globalCompositeOperation = "screen";
        for (let i = 0; i < 13; i++) {
          ctx.strokeStyle = `rgba(208,220,167,${0.01 + Math.sin(time * 0.4 + i) * 0.007})`; ctx.lineWidth = 2 + i % 3;
          ctx.beginPath();
          for (let x = 0; x < w; x += 15) {
            const y = h * 0.1 + i * 10 + Math.sin(x * 0.01 + time * 0.1 + i * 0.9) * 12;
            if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
          }
          ctx.stroke();
        }
        ctx.restore();
        const fishData = packet && packet.timestamp > 0 ? packet.simulation_fish || [] : [
          { bbox: [0.3, 0.375, 0.47, 0.46], heading: 0.06, confidence: 1 },
          { bbox: [0.62, 0.46, 0.77, 0.535], heading: -0.09, confidence: 1 },
          { bbox: [0.1, 0.59, 0.23, 0.66], heading: -0.1, confidence: 1 },
          { bbox: [0.44, 0.67, 0.54, 0.72], heading: 0.02, confidence: 1 },
          { bbox: [0.8, 0.28, 0.9, 0.33], heading: Math.PI, confidence: 1 },
          { bbox: [0.16, 0.25, 0.235, 0.29], heading: 0.02, confidence: 1 },
        ];
        fishData.forEach((f, i) => {
          const [x1, y1, x2, y2] = f.bbox;
          const [x, y] = pos([(x1 + x2) / 2, (y1 + y2) / 2]);
          const idle = !packet || packet.timestamp === 0;
          fish(ctx, x + (idle ? Math.sin(time * 0.24 + i) * 13 : 0), y + (idle ? Math.sin(time * 0.6 + i) * 3 : 0), (x2 - x1) * sw, (y2 - y1) * sh * 1.55, f.heading || 0, time, i + 1);
        });
        for (let i = 0; i < 95; i++) {
          const x = ((i * 191.31 + time * (2 + i % 4)) % (w + 20)) - 10;
          const y = (i * 91.7 + Math.sin(time * 0.2 + i) * 8) % h;
          ctx.fillStyle = `rgba(217,232,190,${0.06 + (i % 6) * 0.015})`; ctx.beginPath(); ctx.arc(x, y, 0.5 + i % 3 * 0.5, 0, Math.PI * 2); ctx.fill();
        }
      }
      const cross = [...(packet?.events || [])].reverse().find(e => e.type === "UPSTREAM_CROSSING" || e.type === "DOWNSTREAM_CROSSING");
      if (cross && cross.id !== lastEvent) { lastEvent = cross.id; gateFlash = time; }
      const flash = Math.max(0, 1 - (time - gateFlash) / 1.4);
      // The same object-cover transform is shared by habitat, gate, tracks and heatmap.
      const [ga, gb] = p.gate.map(pos);
      cv.save(); cv.strokeStyle = `rgba(215,239,201,${p.calibrating ? 0.9 : 0.3 + flash * 0.6})`;
      cv.lineWidth = 1 + flash * 2; cv.setLineDash([4, 7]); cv.beginPath(); cv.moveTo(...ga); cv.lineTo(...gb); cv.stroke(); cv.setLineDash([]);
      for (const pt of [ga, gb]) { cv.fillStyle = p.calibrating ? MINT : "rgba(225,242,206,.65)"; cv.beginPath(); cv.arc(...pt, p.calibrating ? 7 : 3, 0, Math.PI * 2); cv.fill(); if (p.calibrating) { cv.strokeStyle = "rgba(199,238,209,.3)"; cv.lineWidth = 8; cv.stroke(); } }
      const angle = Math.atan2(gb[1] - ga[1], gb[0] - ga[0]);
      cv.translate((ga[0] + gb[0]) / 2 + 15, (ga[1] + gb[1]) / 2); cv.rotate(angle - Math.PI / 2);
      cv.fillStyle = "rgba(212,232,203,.65)"; cv.font = "9px monospace"; cv.textAlign = "center"; cv.letterSpacing = "2px";
      cv.save(); cv.rotate(-Math.PI / 2); cv.fillText(p.calibrating ? "DRAG GATE ENDPOINTS" : "PASSAGE GATE 01", 0, 0); cv.restore(); cv.restore();
      for (const track of p.tracks) {
        const active = track.active ?? ((packet?.timestamp || 0) - track.last_seen < 1.5);
        if (!active && p.mode === "live" && track.id !== p.selected) continue;
        const matches = p.mode === "live" || isVisible(track, p.filter, p.selected);
        const selected = track.id === p.selected;
        const alpha = !matches ? 0.045 : p.selected !== null && !selected ? 0.24 : 1;
        const color = track.reversals > 0 || track.flags.includes("LONG_DWELL") ? AMBER : MINT;
        cv.save(); cv.globalAlpha = alpha;
        const trail = track.trajectory || [];
        if (p.showTrails || p.mode !== "live" || selected) {
          const points = p.mode === "live" && !selected ? trail.slice(-35) : trail;
          if (points.length > 1) {
            cv.lineWidth = selected ? 2.4 : p.mode === "trajectories" ? 1.7 : 1.2; cv.lineCap = "round"; cv.lineJoin = "round";
            // Small segments let older trajectory history fade organically.
            for (let j = 1; j < points.length; j++) {
              cv.globalAlpha = alpha * (0.12 + j / points.length * 0.72); cv.strokeStyle = color;
              cv.beginPath(); cv.moveTo(...pos([points[j - 1][0], points[j - 1][1]])); cv.lineTo(...pos([points[j][0], points[j][1]])); cv.stroke();
            }
          }
        }
        cv.globalAlpha = alpha;
        if ((p.showBoxes && active) || selected) {
          const [x1, y1] = pos([track.bbox[0], track.bbox[1]]), [x2, y2] = pos([track.bbox[2], track.bbox[3]]);
          const bw = x2 - x1, bh = y2 - y1, corner = Math.min(12, bw / 5, bh / 3);
          cv.fillStyle = selected ? "rgba(199,238,209,.08)" : "rgba(199,238,209,.022)"; cv.fillRect(x1, y1, bw, bh);
          cv.strokeStyle = color; cv.lineWidth = selected ? 1.6 : 1;
          cv.beginPath();
          for (const [x, y, sx, sy] of [[x1, y1, 1, 1], [x2, y1, -1, 1], [x1, y2, 1, -1], [x2, y2, -1, -1]]) { cv.moveTo(x, y + corner * sy); cv.lineTo(x, y); cv.lineTo(x + corner * sx, y); }
          cv.stroke();
          cv.fillStyle = "rgba(16,35,29,.76)"; cv.fillRect(x1, y1 - 24, 91, 20);
          cv.font = "10px monospace"; cv.textAlign = "left"; cv.fillStyle = color; cv.fillText(`#${String(track.id).padStart(3, "0")}`, x1 + 6, y1 - 10);
          cv.fillStyle = "rgba(236,239,218,.62)"; cv.fillText(`${Math.round(track.confidence * 100)}%`, x1 + 57, y1 - 10);
          if (track.velocity > 0.004 && track.smoothed_velocity) {
            const speed = Math.hypot(...track.smoothed_velocity) || 1;
            const dx = track.smoothed_velocity[0] / speed, dy = track.smoothed_velocity[1] / speed;
            const ax = dx >= 0 ? x2 + 7 : x1 - 7, ay = (y1 + y2) / 2;
            cv.strokeStyle = color; cv.beginPath(); cv.moveTo(ax, ay); cv.lineTo(ax + dx * 23, ay + dy * 23); cv.lineTo(ax + dx * 18 - dy * 4, ay + dy * 18 + dx * 4); cv.moveTo(ax + dx * 23, ay + dy * 23); cv.lineTo(ax + dx * 18 + dy * 4, ay + dy * 18 - dx * 4); cv.stroke();
          }
        }
        if (p.mode !== "live" && matches) {
          for (const point of track.reversal_locations || []) { const [x, y] = pos(point); cv.strokeStyle = AMBER; cv.lineWidth = 1; cv.beginPath(); cv.arc(x, y, 7, 0, Math.PI * 2); cv.stroke(); cv.fillStyle = AMBER; cv.font = "10px monospace"; cv.textAlign = "center"; cv.fillText("↶", x, y + 3); }
        }
        cv.restore();
      }
      if (lastHeatFrame !== (packet?.frame ?? 0) || lastHeatType !== p.heatmap || lastHeatMode !== p.mode) {
        hm.clearRect(0, 0, w, h); lastHeatFrame = packet?.frame ?? 0; lastHeatType = p.heatmap; lastHeatMode = p.mode;
        if (p.mode === "behavior" && packet?.heatmaps) {
          const grid = packet.heatmaps[p.heatmap], maximum = Math.max(0.01, ...grid.flat());
          hm.save(); hm.globalCompositeOperation = "screen";
          grid.forEach((row, yi) => row.forEach((value, xi) => {
            if (value <= 0) return;
            const [x, y] = pos([(xi + 0.5) / packet.heatmaps.columns, (yi + 0.5) / packet.heatmaps.rows]);
            const strength = Math.sqrt(value / maximum), radius = sw / packet.heatmaps.columns * 1.7;
            const gradient = hm.createRadialGradient(x, y, 0, x, y, radius);
            gradient.addColorStop(0, p.heatmap === "density" ? `rgba(119,211,181,${strength * 0.35})` : `rgba(240,145,78,${strength * 0.4})`);
            gradient.addColorStop(0.45, p.heatmap === "density" ? `rgba(75,174,145,${strength * 0.16})` : `rgba(211,173,64,${strength * 0.15})`);
            gradient.addColorStop(1, "rgba(0,0,0,0)"); hm.fillStyle = gradient; hm.fillRect(x - radius, y - radius, radius * 2, radius * 2);
          })); hm.restore();
        }
      }
      if (p.mode === "behavior" && packet?.heatmaps.hotspot) {
        const spot = packet.heatmaps.hotspot;
        const [hx, hy] = pos([spot.x, spot.y]);
        cv.save(); cv.strokeStyle = "rgba(240,185,129,.8)"; cv.lineWidth = 1;
        cv.setLineDash([3, 5]); cv.beginPath(); cv.ellipse(hx, hy, sw / packet.heatmaps.columns * 1.5, sh / packet.heatmaps.rows * 1.5, 0, 0, Math.PI * 2); cv.stroke();
        cv.setLineDash([]); cv.fillStyle = AMBER; cv.font = "8px monospace"; cv.textAlign = "center";
        cv.fillText("OBSERVED REGION", hx, hy - sh / packet.heatmaps.rows * 1.5 - 8); cv.restore();
      }
      animation = requestAnimationFrame(draw);
    };
    animation = requestAnimationFrame(draw);
    return () => { cancelAnimationFrame(animation); observer.disconnect(); };
  }, []);

  const normalize = (event: React.PointerEvent<HTMLCanvasElement>): Point => {
    const v = viewport.current, box = event.currentTarget.getBoundingClientRect();
    return [Math.min(1, Math.max(0, (event.clientX - box.left - v.ox) / (v.sourceW * v.scale))), Math.min(1, Math.max(0, (event.clientY - box.top - v.oy) / (v.sourceH * v.scale)))];
  };
  return <>
    <canvas ref={sceneRef} className="scene-canvas" aria-hidden="true" />
    <div className={`scene-shade ${props.mode !== "live" ? "scene-shade-analysis" : ""}`} />
    <canvas ref={heatRef} className="heat-canvas" aria-hidden="true" />
    <canvas ref={overlayRef} className={`cv-canvas ${props.calibrating ? "calibrating" : ""}`} aria-label="Salmon tracking overlay. Select a fish to inspect its journey."
      onPointerDown={event => {
        const point = normalize(event);
        if (props.calibrating) {
          const distances = props.gate.map(p => Math.hypot((p[0] - point[0]) * viewport.current.sourceW * viewport.current.scale, (p[1] - point[1]) * viewport.current.sourceH * viewport.current.scale));
          const nearest = distances[0] < distances[1] ? 0 : 1;
          if (distances[nearest] < 35) { dragging.current = nearest; event.currentTarget.setPointerCapture(event.pointerId); }
          return;
        }
        const track = [...props.tracks].reverse().find(t => (t.active || props.mode !== "live") && point[0] >= t.bbox[0] - 0.015 && point[0] <= t.bbox[2] + 0.015 && point[1] >= t.bbox[1] - 0.015 && point[1] <= t.bbox[3] + 0.015);
        props.onSelect(track?.id ?? null);
      }}
      onPointerMove={event => {
        if (dragging.current !== null) { const gate: Gate = [[...props.gate[0]], [...props.gate[1]]]; gate[dragging.current] = normalize(event); props.onGateChange(gate); }
      }}
      onPointerUp={() => { dragging.current = null; }}
      onPointerCancel={() => { dragging.current = null; }}
    />
  </>;
}
