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
});
