/**
 * Live end-to-end suite — Phase 23 A4.
 *
 * Unlike the default suite, these tests start *real* builds against a *real*
 * backend and therefore spend real Groq quota. That is why they live in their
 * own Playwright project (`live`), are excluded from `npm run test:e2e`, and
 * are run deliberately:
 *
 *   1. venv/Scripts/python.exe start_server.py     # backend, port 8000
 *   2. npm run test:e2e:live                       # this file only
 *
 * The backend is still not owned by the test runner (see playwright.config.ts):
 * it holds a database and a worker pool, and a suite that tore that down
 * between runs would be destroying state the rest of the project depends on.
 * Every test here therefore *skips* rather than fails when the backend is
 * absent, so an unstarted server reads as "not run", never as "broken".
 */
import { test, expect, type Page } from '@playwright/test';
import { backendUp, collectFailedRequests } from './helpers';

/** A prompt small enough to keep the quota cost of the cancel test honest. */
const CHEAP_PROMPT =
  'A single-endpoint FastAPI service that returns the current time as JSON.';

test.beforeEach(async ({ page }) => {
  test.skip(!(await backendUp(page)), 'Backend is not running on :8000 — start it first.');
});

/** Submit the composer and land on /build/{id}, returning the build id. */
async function startBuild(page: Page, prompt: string): Promise<string> {
  await page.goto('/build');
  await page.fill('#build-prompt-input', prompt);
  await page.click('#start-build-btn');
  await page.waitForURL(/\/build\/[0-9a-f-]{36}/, { timeout: 30_000 });
  const id = page.url().split('/build/')[1];
  expect(id).toMatch(/^[0-9a-f-]{36}$/);
  return id;
}

/** Cancel via the page's own button, answering its confirm() dialog. */
async function cancel(page: Page) {
  const button = page.getByRole('button', { name: /Cancel build/i });
  if (!(await button.count())) return;
  page.once('dialog', d => d.accept());
  await button.click();
}

test.describe('live build lifecycle', () => {
  /**
   * The WebSocket is the point of this test. `useBuildProgress` falls back to
   * a 5s poll when the socket fails, and the page looks *identical* either way
   * — steps still fill in, just later. The pill is the only place the
   * distinction surfaces, so it is what we assert on: "Live" means the socket
   * carried the transition, "Polling" means it did not.
   */
  test('WebSocket step transitions land in StepTracker, not the poll fallback', async ({ page }) => {
    const failed = collectFailedRequests(page);
    await startBuild(page, CHEAP_PROMPT);

    // The socket connects before any step arrives.
    await expect(page.getByText('Live', { exact: true })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText('Polling', { exact: true })).toHaveCount(0);

    // A step reaches `running` and then leaves it — a transition, not just an
    // initial render. Both halves must happen while the pill still says Live.
    await expect(page.locator('.srow--running')).toHaveCount(1, { timeout: 60_000 });
    const firstRunning = await page.locator('.srow--running .srow__name').first().textContent();

    await expect
      .poll(() => page.locator('.srow--done, .srow--done_with_context').count(),
            { timeout: 180_000, intervals: [1000] })
      .toBeGreaterThan(0);

    await expect(page.getByText('Live', { exact: true })).toBeVisible();
    expect(firstRunning, 'a named step should have been running').toBeTruthy();

    // Housekeeping: this test does not need the build to finish.
    await cancel(page);
    expect(failed, 'no 5xx or failed requests during a live build').toEqual([]);
  });

  /**
   * The regression this locks down: a cancelled build used to fall through to
   * the success branch and announce "Build complete — your files are ready to
   * download", which was false in every particular.
   */
  test('cancel mid-build yields cancelled, and never claims the build completed', async ({ page }) => {
    await startBuild(page, CHEAP_PROMPT);
    await expect(page.locator('.srow--running')).toHaveCount(1, { timeout: 60_000 });

    await cancel(page);

    await expect(page.getByRole('heading', { name: 'Build cancelled' }))
      .toBeVisible({ timeout: 60_000 });
    await expect(page.getByText('Cancelled before completion')).toBeVisible();

    // The claim that must not appear, asserted on both halves of the wording.
    await expect(page.getByRole('heading', { name: 'Build complete' })).toHaveCount(0);
    await expect(page.getByText(/files are ready to download/i)).toHaveCount(0);
    // Nothing was packaged, so nothing may be offered.
    await expect(page.locator('#download-zip-btn')).toHaveCount(0);
  });
});

test.describe('downloads', () => {
  /**
   * Building an app just to download it would cost a full quota run per
   * execution, so this reuses a build the platform has already completed. If
   * there is not one yet, the test skips rather than inventing a fixture — a
   * fake ZIP would prove nothing about the packaging path.
   */
  test('the ZIP downloads and is a valid archive', async ({ page }) => {
    const res = await page.request.get('/projects/?limit=50');
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    const projects = Array.isArray(body) ? body : (body.projects ?? []);
    const finished = projects.find(
      (p: { status: string }) => p.status === 'done' || p.status === 'done_with_context'
    );
    test.skip(!finished, 'No completed build exists yet to download.');

    await page.goto(`/projects/${finished.build_id}`);
    const button = page.locator('#download-zip-btn');
    await expect(button).toBeVisible();

    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 60_000 }),
      button.click(),
    ]);
    const path = await download.path();
    expect(path, 'download produced a file').toBeTruthy();

    // "Valid archive" means the ZIP local-file-header magic, not just a
    // non-zero byte count — a JSON error page also has a non-zero size.
    const fs = await import('node:fs/promises');
    const head = (await fs.readFile(path!)).subarray(0, 4);
    expect(Array.from(head)).toEqual([0x50, 0x4b, 0x03, 0x04]);
  });
});

/**
 * The quota-handoff path (Phase 21) on the *current* models.
 *
 * This needs the backend started with the A3 switch on, which the test runner
 * cannot do to a server it does not own:
 *
 *   GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS=3 venv/Scripts/python.exe start_server.py
 *   LIVE_QUOTA_SIM=1 npm run test:e2e:live
 *
 * Without `LIVE_QUOTA_SIM` the test skips, because against a normal server it
 * would simply wait out a full successful build and then fail on a banner that
 * was never supposed to appear.
 */
test.describe('simulated quota exhaustion', () => {
  test('the handoff banner renders and the download stays available', async ({ page }) => {
    test.skip(!process.env.LIVE_QUOTA_SIM,
      'Set LIVE_QUOTA_SIM=1 and start the backend with GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS.');

    const id = await startBuild(page, CHEAP_PROMPT);

    await expect(page.getByRole('heading', { name: 'Finished with notes' }))
      .toBeVisible({ timeout: 300_000 });
    await expect(page.getByText('Finished with a handoff document')).toBeVisible();

    // The whole point of `done_with_context`: degraded, but still shippable.
    await page.goto(`/projects/${id}`);
    await expect(page.locator('#download-zip-btn')).toBeEnabled();
  });
});
