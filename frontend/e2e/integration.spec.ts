import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { ROUTES } from './helpers';

/**
 * Contract tests: does the backend actually serve what the client calls?
 *
 * These run against the live API through the dev proxy, so they fail when the
 * two drift apart — a renamed route, a changed method, a path that has been
 * shadowed by another router.
 */

/** Every endpoint api/client.ts calls, read out of the source. */
function declaredEndpoints(): string[] {
  const src = readFileSync(join(process.cwd(), 'src/api/client.ts'), 'utf8');
  const paths = new Set<string>();
  for (const m of src.matchAll(/`\$\{BASE_URL\}(\/[^`$]*)/g)) paths.add(m[1]);
  for (const m of src.matchAll(/request<[^>]*>\(\s*`([^`]*)`/g)) paths.add(m[1]);
  for (const m of src.matchAll(/request<[^>]*>\(\s*'([^']*)'/g)) paths.add(m[1]);
  return [...paths];
}

test.describe('API contract', () => {
  test('the client calls no endpoint the backend does not serve', async ({ request }) => {
    const spec = await (await request.get('/openapi.json')).json();
    const served: string[] = Object.keys(spec.paths ?? {});
    expect(served.length, 'no OpenAPI paths — is the backend running?').toBeGreaterThan(5);

    // Turn "/projects/{build_id}" into a matcher for "/projects/anything".
    const matchers = served.map(p =>
      new RegExp('^' + p.replace(/\{[^}]+\}/g, '[^/]+').replace(/\//g, '\\/') + '$')
    );

    const missing = declaredEndpoints()
      .map(p => p.replace(/\$\{[^}]*\}/g, 'X').split('?')[0])
      .filter(p => p.startsWith('/'))
      .filter(p => !matchers.some(re => re.test(p)));

    expect(missing, 'client paths with no matching backend route').toEqual([]);
  });

  test('every route the app links to answers', async ({ request }) => {
    for (const path of ['/health', '/stats', '/projects/', '/jobs/queue', '/jobs/active']) {
      const res = await request.get(path);
      expect(res.status(), `GET ${path}`).toBe(200);
    }
  });
});

test.describe('the shadowed cleanup route', () => {
  /**
   * `DELETE /projects/cleanup` was permanently unreachable: `projects.router`
   * was registered first and its `DELETE /projects/{build_id}` swallowed
   * "cleanup" as a build id. Registering analytics first fixes it.
   */
  test('DELETE /projects/cleanup reaches the cleanup handler', async ({ request }) => {
    const res = await request.delete('/projects/cleanup', {
      // dry_run so this asserts routing without deleting anything.
      data: { older_than_days: 3650, statuses: ['failed'], dry_run: true },
    });

    expect(res.status()).toBe(200);
    const body = await res.json();

    // The cleanup handler's shape. A build-id lookup would 404 or return a
    // project object instead.
    expect(body).toHaveProperty('dry_run', true);
    expect(body).toHaveProperty('would_delete');
    expect(body).not.toHaveProperty('build_id');
  });
});

test.describe('the prompt limit', () => {
  /**
   * The composer allowed 2000 while the API rejected above 500 with a 422 the
   * user never saw explained. Asserted against the live schema rather than by
   * submitting — a real POST would start a build.
   */
  test('the API accepts the same 2000 characters the composer does', async ({ request }) => {
    const spec = await (await request.get('/openapi.json')).json();
    const prompt = spec.components.schemas.BuildRequest.properties.prompt;

    expect(prompt.maxLength).toBe(2000);

    // And the frontend agrees.
    const promptTs = readFileSync(join(process.cwd(), 'src/lib/prompt.ts'), 'utf8');
    const clientMax = Number(/MAX_CHARS = (\d+)/.exec(promptTs)?.[1]);
    expect(clientMax).toBe(prompt.maxLength);
  });

  /**
   * Opt-in: `E2E_LIVE_BUILD=1 npm run test:e2e`.
   *
   * This is the only test in the suite that POSTs a real build, and a real
   * build spends real LLM quota — on an account whose keys are rate-limited
   * daily, that is not something a routine test run should do. The schema
   * assertion above already proves the limit is 2000 on both sides; this
   * proves the request survives the whole validation path, which is worth
   * running deliberately and not by accident.
   */
  test('a 2000-character prompt passes validation', async ({ request }) => {
    test.skip(!process.env.E2E_LIVE_BUILD, 'set E2E_LIVE_BUILD=1 to POST a real build');

    // 422 is the failure we are guarding against. Any other status means the
    // body got past validation, which is all this asserts.
    const res = await request.post('/projects/', {
      data: { prompt: 'x'.repeat(2000) },
      failOnStatusCode: false,
    });
    expect(res.status(), 'a 2000-char prompt was rejected by validation').not.toBe(422);

    // Do not leave a real build running.
    if (res.status() === 202 || res.status() === 200) {
      const { build_id } = await res.json();
      if (build_id) {
        await request.delete(`/jobs/${build_id}`, { failOnStatusCode: false });
        await request.delete(`/projects/${build_id}`, { failOnStatusCode: false });
      }
    }
  });

  test('a prompt over the limit is still rejected', async ({ request }) => {
    const res = await request.post('/projects/', {
      data: { prompt: 'x'.repeat(2001) },
      failOnStatusCode: false,
    });
    expect(res.status()).toBe(422);
  });
});

test.describe('deep links', () => {
  test('a client-side route resolves from the SPA mount', async ({ request }) => {
    // Served by the backend directly, with no dev server in the picture: this
    // is the "one command serves the whole product" path.
    const res = await request.get('http://localhost:8000' + ROUTES.detail, {
      headers: { accept: 'text/html' },
    });
    expect(res.status()).toBe(200);
    expect((await res.text()).toLowerCase()).toContain('<!doctype html');
  });

  test('the same path still returns JSON to the app', async ({ request }) => {
    // The Accept split is what makes both possible. If this ever returns HTML,
    // every fetch in the product breaks.
    const res = await request.get('http://localhost:8000' + ROUTES.detail, {
      headers: { accept: 'application/json' },
    });
    expect(res.status()).toBe(200);
    expect(res.headers()['content-type']).toContain('application/json');
    expect(await res.json()).toHaveProperty('build_id');
  });

  test('an unknown client route still gets the shell, not a 404', async ({ request }) => {
    const res = await request.get('http://localhost:8000/dashboard', {
      headers: { accept: 'text/html' },
    });
    expect(res.status()).toBe(200);
    expect((await res.text()).toLowerCase()).toContain('<!doctype html');
  });
});

test.describe('the full journey', () => {
  test('dashboard → detail → rebuild dialog', async ({ page }) => {
    await page.goto(ROUTES.dashboard);
    await page.waitForLoadState('networkidle');

    const firstBuild = page.locator('.build-card').first();
    await expect(firstBuild).toBeVisible();
    await firstBuild.click();

    await expect(page).toHaveURL(/\/projects\//);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    await page.getByRole('button', { name: /Rebuild/i }).first().click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    // Escape must close it — this had no keyboard dismissal at all before.
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();
  });

  test('a cancelled build does not claim it completed', async ({ page }) => {
    await page.goto(ROUTES.cancelled);
    await page.waitForLoadState('networkidle');

    await expect(page.getByRole('heading', { level: 1 })).toContainText('Build cancelled');
    await expect(page.getByText(/ready to download/)).toHaveCount(0);
  });

  test('the new-build composer accepts 2000 characters', async ({ page }) => {
    await page.goto(ROUTES.newBuild);
    const field = page.getByLabel(/Your app/);
    await field.fill('x'.repeat(2000));

    await expect(page.getByText('2000 / 2000')).toBeVisible();
    await expect(page.getByRole('button', { name: /Build app/ })).toBeEnabled();
  });
});
