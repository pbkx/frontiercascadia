import { test, expect } from '@playwright/test';

test('offline visualization follows fish through passage, trajectories and behavior', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => {
    const hostname = new URL(route.request().url()).hostname;
    return ['localhost', '127.0.0.1'].includes(hostname) ? route.continue() : route.abort();
  });
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'START ANALYSIS', exact: false })).toBeEnabled();
  await expect(page.getByText('SIMULATED DATA', { exact: true })).toBeVisible();
  const canvas = page.locator('.cv-canvas');
  const box = await canvas.boundingBox();
  expect(box?.width).toBe(1440);
  expect(box?.height).toBe(900);
  await page.screenshot({ path: 'test-results/observatory.png' });
  await page.getByRole('button', { name: 'START ANALYSIS', exact: false }).click();
  await expect(page.getByRole('button', { name: 'PAUSE ANALYSIS' })).toBeVisible();
  await expect.poll(async () => page.locator('.big-stat').innerText(), { timeout: 25_000 }).not.toMatch(/^00/);
  await expect.poll(async () => page.locator('.behavior-grid > div').first().innerText(), { timeout: 25_000 }).not.toMatch(/Reversals\s*00/);
  await page.getByRole('button', { name: 'Trajectories', exact: true }).click();
  await page.getByRole('button', { name: 'Reversals', exact: true }).click();
  await expect(page.locator('.trajectory-filters button.active')).toHaveText('Reversals');
  await page.screenshot({ path: 'test-results/trajectories.png' });
  await expect(page.locator('.activity-event').first()).toBeVisible();
  await page.locator('.activity-event').first().click();
  await expect(page.locator('.selected-panel')).toBeVisible();
  await expect(page.locator('.selected-panel')).toContainText('Passage attempts');
  await page.getByRole('button', { name: 'Close fish details' }).click();
  await page.getByRole('button', { name: 'Behavior', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Behavior friction' })).toBeVisible();
  await expect(page.locator('.hotspot-callout')).toBeVisible({ timeout: 25_000 });
  await page.screenshot({ path: 'test-results/behavior.png' });
  await page.getByRole('button', { name: 'Movement density' }).click();
  await expect(page.locator('.heatmap-switch button.active')).toContainText('Movement density');
  await page.getByRole('button', { name: 'PAUSE ANALYSIS' }).click();
  await expect(page.getByRole('button', { name: 'RESUME ANALYSIS' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('source chooser, science, calibration and narrow viewport remain usable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'START ANALYSIS', exact: false })).toBeEnabled();
  await expect(page.locator('.view-switch')).toBeVisible();
  await page.screenshot({ path: 'test-results/mobile.png', fullPage: true });
  await page.getByRole('button', { name: 'Open analysis settings' }).click();
  await page.getByRole('button', { name: 'Upstream left' }).click();
  await page.getByRole('button', { name: 'SAVE CALIBRATION' }).click();
  await expect(page.locator('.settings-panel')).not.toBeVisible();
  await page.getByRole('button', { name: 'ANALYZE YOUR FOOTAGE', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('button', { name: 'TRY ISSAQUAH DEMO' })).toBeVisible();
  await page.getByRole('button', { name: 'Close dialog' }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
