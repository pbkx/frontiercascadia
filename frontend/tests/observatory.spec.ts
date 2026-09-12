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
  await analyticsButton.click();
  await expect(page.getByRole('dialog', { name: 'Analytics' })).toBeVisible();
  await expect(page.locator('.video-layer')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Analytics summary' })).toBeVisible();
  await expect(page.getByText('Median speed · widths/s', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Activity', exact: true })).toHaveCSS('color', 'rgb(255, 255, 255)');
  await page.getByRole('button', { name: '5 MIN', exact: true }).click();
  await expect(page.getByRole('button', { name: '5 MIN', exact: true })).toHaveClass(/active/);
  await expect(page.getByRole('button', { name: '5 MIN', exact: true })).toHaveCSS('background-color', 'rgba(255, 255, 255, 0.14)');
  await expect(page.getByRole('button', { name: '5 MIN', exact: true })).toHaveCSS('color', 'rgb(255, 255, 255)');
  await page.getByRole('button', { name: 'Behavior events', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Behavior events', exact: true })).toHaveCSS('color', 'rgb(255, 255, 255)');
  await expect(page.getByRole('heading', { name: 'Behavior Events', level: 3 })).toBeVisible();
  await expect(page.getByText(/NaN|undefined|Infinity/)).toHaveCount(0);
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
