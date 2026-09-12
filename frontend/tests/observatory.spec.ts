import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { test, expect } from '@playwright/test';

const fixture = path.resolve('test-results/local-video-fixture.avi');

test.beforeAll(() => {
  mkdirSync(path.dirname(fixture), { recursive: true });
  const python = path.resolve('../.venv/bin/python');
  execFileSync(python, ['-c', [
    'import cv2, numpy as np, sys',
    'w=cv2.VideoWriter(sys.argv[1], cv2.VideoWriter_fourcc(*"MJPG"), 15, (640,360))',
    'assert w.isOpened()',
    '[(w.write(cv2.putText(np.full((360,640,3), 25+i%30, np.uint8), "LOCAL VIDEO FIXTURE", (125,180), cv2.FONT_HERSHEY_SIMPLEX, .8, (190,220,210), 2))) for i in range(150)]',
    'w.release()',
  ].join(';'), fixture]);
});

test('opens video-first and analyzes a real local video fixture', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');

  await expect(page.getByText('https://www.youtube.com/watch?v=tWFigWkp98o', { exact: true })).toBeVisible({ timeout: 60_000 });
  await expect(page.locator('.video-layer')).toBeVisible();
  await expect(page.locator('.live-status')).toHaveText('LIVE');
  await expect(page.locator('.live-status')).toHaveCSS('color', 'rgb(255, 69, 58)');
  await expect(page.locator('.live-status i')).toHaveCSS('animation-name', 'live-blink');
  await expect(page.getByLabel('Video position')).toHaveCount(0);
  await expect(page.getByText('Every journey, in sight.')).toHaveCount(0);
  await expect(page.getByText('A river, reimagined.')).toHaveCount(0);
  const overlay = page.locator('.cv-canvas');
  const video = page.locator('.video-layer');
  await expect(overlay).toHaveCSS('width', await video.evaluate(element => `${element.getBoundingClientRect().width}px`));

  await page.getByRole('button', { name: 'Change source' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByLabel('YouTube URL')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Issaquah SalmonCam' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Upload MP4 / MOV / AVI' })).toBeVisible();
  await expect(page.getByText('MP4, MOV, and supported AVI files run through the same local detector and tracker.')).toHaveCount(0);
  const connectButton = page.getByRole('button', { name: 'Connect', exact: true });
  await expect(connectButton).toHaveCSS('background-color', 'rgba(255, 255, 255, 0.94)');
  await expect(connectButton).toHaveCSS('color', 'rgb(5, 5, 5)');
  expect((await connectButton.boundingBox())!.width).toBeCloseTo((await page.getByLabel('YouTube URL').boundingBox())!.width, 0);
  await page.locator('input[type=file]').setInputFiles(fixture);
  await expect(page.getByRole('complementary', { name: 'Calibration settings' })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('local-video-fixture.avi', { exact: true })).toBeVisible();
  await expect(page.getByText('VIDEO STREAM', { exact: true })).toHaveCount(0);
  await expect(page.locator('.source-state strong')).toHaveCount(0);
  await expect(page.locator('.live-status')).toHaveCount(0);
  await expect(page.getByLabel('Video position')).toHaveCount(0);
  await page.getByRole('button', { name: 'Upstream left' }).click();
  await page.getByRole('button', { name: 'Save calibration' }).click();
  await expect(page.getByRole('button', { name: 'Pause analysis' })).toBeVisible({ timeout: 30_000 });

  const playbackPosition = page.getByLabel('Video position');
  await expect(playbackPosition).toBeVisible();
  await page.getByRole('button', { name: 'Pause video' }).click();
  await expect(page.getByRole('button', { name: 'Play video' })).toBeVisible();
  const frozenMetrics = await page.getByRole('region', { name: 'Tracking metrics' }).textContent();
  await page.waitForTimeout(350);
  expect(await page.getByRole('region', { name: 'Tracking metrics' }).textContent()).toBe(frozenMetrics);
  await playbackPosition.fill('2');
  await expect(playbackPosition).toHaveValue('2');
  await page.waitForTimeout(400);
  expect(await page.getByRole('region', { name: 'Tracking metrics' }).textContent()).toBe(frozenMetrics);
  await page.getByRole('button', { name: 'Play video' }).click();
  await expect(page.getByRole('button', { name: 'Pause video' })).toBeVisible();

  await page.getByRole('button', { name: 'trajectories', exact: true }).click();
  await expect(page.getByRole('group', { name: 'Trajectory filters' })).toBeVisible();
  await page.getByRole('button', { name: 'Upstream', exact: true }).click();
  await page.getByRole('button', { name: 'behavior', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Movement density' })).toBeVisible();
  await page.getByRole('button', { name: 'Dwell hotspot' }).click();
  const analyticsButton = page.getByRole('button', { name: 'Analytics', exact: true });
  const sourceButton = page.getByRole('button', { name: 'Change source', exact: true });
  expect((await analyticsButton.boundingBox())!.x).toBeLessThan((await sourceButton.boundingBox())!.x);
  await page.route('**/api/sessions/*/analytics?range=*', route => route.fulfill({ json: {
    session_id: 'csv-session', source_type: 'upload', source_name: 'local-video-fixture.avi', range: 'all',
    observation: { start: 0, end: 12, seconds: 12, bucket_seconds: 30 },
    summary: { fish_tracked: 1, upstream_percent: 100, downstream_percent: 0, reversal_rate: 0, median_observed_time: 8.2, median_relative_speed: .19 },
    findings: ['100% of directional tracks moved upstream.'],
    activity: [{ start: 0, end: 12, fish_observed: 1, upstream_crossings: 1, downstream_crossings: 0 }],
    behavior_events: [{ start: 0, end: 12, reversals: 0, long_dwell: 0 }],
    direction: [{ name: 'upstream', count: 1, percent: 100 }, { name: 'downstream', count: 0, percent: 0 }, { name: 'uncertain', count: 0, percent: 0 }],
    observed_time_distribution: [{ label: '5–10 sec', min: 5, max: 10, count: 1 }],
    observed_time_stats: { median: 8.2, p90: 8.2, longest: 8.2 },
    speed_distribution: [{ label: '0.15–0.20', min: .15, max: .2, count: 1 }],
    speed_stats: { median: .19, p90: .19 },
    normal_vs_reversal: {
      normal: { count: 1, median_observed_time: 8.2, median_relative_speed: .19, median_distance: .74, upstream_crossing_rate: 100 },
      reversal: { count: 0, median_observed_time: null, median_relative_speed: null, median_distance: null, upstream_crossing_rate: null },
    },
    scatter: [{ id: 184, display_id: 1, speed: .19, observed_time: 8.2, reversal: false }],
    tracks: [{ id: 184, display_id: 1, direction: 'upstream', observed_time: 8.2, relative_speed: .19, distance: .74, reversals: 0, crossed: true, first_seen: 3.8 }],
  } }));
  await analyticsButton.click();
  await expect(page.getByRole('dialog', { name: 'Analytics' })).toBeVisible();
  await expect(page.locator('.video-layer')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Analytics summary' })).toBeVisible();
  await expect(page.getByText('Median speed', { exact: true })).toBeVisible();
  await expect(page.getByText(/widths\/s|frame widths \/ second/)).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Activity', exact: true })).toHaveCSS('color', 'rgb(255, 255, 255)');
  await page.getByRole('button', { name: '5 MIN', exact: true }).click();
  await expect(page.getByRole('button', { name: '5 MIN', exact: true })).toHaveClass(/active/);
  await expect(page.getByRole('button', { name: '5 MIN', exact: true })).toHaveCSS('background-color', 'rgba(255, 255, 255, 0.14)');
  await expect(page.getByRole('button', { name: '5 MIN', exact: true })).toHaveCSS('color', 'rgb(255, 255, 255)');
  await page.getByRole('button', { name: 'Behavior events', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Behavior events', exact: true })).toHaveCSS('color', 'rgb(255, 255, 255)');
  await expect(page.getByRole('heading', { name: 'Behavior Events', level: 3 })).toBeVisible();
  await expect(page.getByText(/NaN|undefined|Infinity/)).toHaveCount(0);
  await page.getByRole('button', { name: 'Tracks', exact: true }).click();
  const exportButton = page.getByRole('button', { name: 'Export CSV' });
  await expect(exportButton).toBeEnabled();
  const [download] = await Promise.all([page.waitForEvent('download'), exportButton.click()]);
  expect(download.suggestedFilename()).toBe('fyolo-tracks-5m.csv');
  const csv = await (await download.createReadStream()).toArray();
  const csvText = Buffer.concat(csv).toString('utf8');
  expect(csvText).toContain('"Track","Direction","Observed seconds","Relative speed","Distance","Reversals","Crossed","First seen seconds"');
  expect(csvText).toContain('"1","upstream","8.2","0.19","0.74","0","true","3.8"');
  const workspaceBox = await page.locator('.tracks-workspace').boundingBox();
  const tableBox = await page.locator('.table-scroll').boundingBox();
  expect(Math.abs(workspaceBox!.y + workspaceBox!.height - tableBox!.y - tableBox!.height)).toBeLessThan(2);
  await page.getByRole('button', { name: 'Close analytics' }).click();
  await expect(page.getByRole('dialog', { name: 'Analytics' })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('source controls and overlays remain usable on a narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.locator('.cv-canvas')).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Main modes' })).toBeVisible();
  await page.getByRole('button', { name: 'Open calibration settings' }).click();
  await expect(page.getByRole('complementary', { name: 'Calibration settings' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Close calibration settings' }).click();
  await page.getByRole('button', { name: 'Analytics', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Analytics' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Close analytics' }).click();
});

test('selection follows the visible tracks and clears when changing modes', async ({ page }) => {
  const track = (id: number, displayId: number, bbox: [number, number, number, number], active: boolean) => ({
    id, display_id: displayId, bbox, centroid: [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2],
    confidence: .91, trajectory: [[bbox[0], bbox[1], 9]], smoothed_velocity: [.02, 0],
    velocity: .02, direction: 'upstream', time_observed: 3, reversals: 0,
    reversal_locations: [], dwell_time: .2, attempts: 0, status: 'ACTIVE', flags: [],
    last_seen: active ? 10 : 2, active,
  });
  const snapshot = {
    session: {
      id: 'selection-session', mode: 'VISUALIZATION_DEMO', label: 'SIMULATED DATA',
      source_name: 'Selection fixture', source_origin: 'Selection fixture', running: false,
      completed: false, error: null, detector_state: 'ILLUSTRATIVE', video_url: null,
      width: 1440, height: 900, source_type: 'simulated', passage_calibrated: false,
      reconnecting: false, reconnect_attempts: 0, display_fps: 10, stream_active: false,
      seekable: false, playback_paused: false, playback_position: 0, analysis_generation: 0,
      calibration_required: false,
      calibration: { upstream: [1, 0], gate: [[.65, .26], [.65, .74]] },
    },
    frame: 100, timestamp: 10, processing_fps: 8.4,
    tracks: [track(10_000_794, 1, [.10, .10, .20, .20], true), track(10_000_795, 2, [.70, .10, .80, .20], false)],
    summary: {
      upstream: 0, downstream: 0, active: 1, passage_rate: null, successful: 0,
      attempts: 0, reversals: 0, long_dwell: 0, success_rate: null,
      median_passage_seconds: null, elapsed_seconds: 10, tracks_produced: 2,
    },
    events: [],
    heatmaps: {
      density: [[0]], friction: [[0]], columns: 1, rows: 1, hotspot: null,
    },
    simulation_fish: [],
  };

  await page.route('**/api/sessions', async route => {
    await route.fulfill({ json: snapshot });
  });
  await page.routeWebSocket('**/ws/sessions/**', () => undefined);
  await page.goto('/');

  const overlay = page.locator('.cv-canvas');
  await expect(overlay).toBeVisible();
  const clickNormalized = async (x: number, y: number) => {
    const bounds = await overlay.boundingBox();
    if (!bounds) throw new Error('Tracking canvas has no bounds');
    await overlay.click({ position: { x: bounds.width * x, y: bounds.height * y } });
  };

  await clickNormalized(.15, .15);
  await expect(page.getByRole('complementary', { name: 'Fish 1 details' })).toBeVisible();
  await page.getByRole('button', { name: 'trajectories', exact: true }).click();
  await expect(page.getByRole('complementary', { name: 'Fish 1 details' })).toHaveCount(0);

  await clickNormalized(.15, .15);
  await expect(page.getByRole('complementary', { name: 'Fish 1 details' })).toBeVisible();
  await page.getByRole('button', { name: 'trajectories', exact: true }).click();
  await expect(page.getByRole('complementary', { name: 'Fish 1 details' })).toHaveCount(0);

  await clickNormalized(.15, .15);
  await expect(page.getByRole('complementary', { name: 'Fish 1 details' })).toBeVisible();
  await page.getByRole('button', { name: 'behavior', exact: true }).click();
  await expect(page.getByRole('complementary', { name: 'Fish 1 details' })).toHaveCount(0);

  await clickNormalized(.75, .15);
  await expect(page.locator('.track-panel')).toHaveCount(0);
  await page.getByRole('button', { name: 'live', exact: true }).click();
  await clickNormalized(.75, .15);
  await expect(page.locator('.track-panel')).toHaveCount(0);

  await clickNormalized(.15, .15);
  await expect(page.getByRole('complementary', { name: 'Fish 1 details' })).toBeVisible();
  await clickNormalized(.5, .5);
  await expect(page.locator('.track-panel')).toHaveCount(0);
});
