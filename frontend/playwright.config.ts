import { defineConfig, devices } from '@playwright/test';

/**
 * E2E runs against the real Vite dev server, which proxies the API to the
 * backend on 8000 (see vite.config.ts). The backend is NOT started here — it
 * owns a database and a worker pool, and a test runner should not be launching
 * something with that much state. Start it yourself:
 *
 *   venv/Scripts/python.exe start_server.py
 *
 * The suite reports clearly when it is not running rather than failing with a
 * wall of connection errors.
 */
/**
 * Phase 23 A4: the `live` project is only *declared* when it is explicitly
 * asked for.
 *
 * `testIgnore` on the default project is not enough on its own — it keeps
 * live.spec.ts out of `chromium`, but a bare `playwright test` still runs
 * every declared project, so `live` would execute anyway and start real
 * builds against real Groq quota. Omitting the project entirely is the only
 * way to make "run everything" mean "run everything that is free".
 */
const LIVE_REQUESTED = process.argv.some(
  (arg, i) => arg === '--project=live' || (arg === '--project' && process.argv[i + 1] === 'live')
);

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list']],

  use: {
    /**
     * `localhost`, not `127.0.0.1`. Vite's default binding resolves to IPv6
     * `::1` on this machine and does not listen on IPv4 at all, so
     * `http://127.0.0.1:5173` is refused at the socket — before CORS, before
     * the proxy, before any app code runs. `localhost` is the spelling that
     * works on both stacks. Add `--host` to `npm run dev` if you need the
     * literal IPv4 address (it also exposes the server on your network).
     */
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    /**
     * The default project. `live.spec.ts` is excluded on purpose: it starts
     * real builds and spends real Groq quota, which `npm run test:e2e` must
     * never do as a side effect of checking the UI.
     */
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
      testIgnore: /live\.spec\.ts/,
    },
    /**
     * Phase 23 A4 — opt-in only, via `npm run test:e2e:live`. Needs the
     * backend already running on :8000; the specs skip themselves when it is
     * not, so "backend down" reads as not-run rather than as broken.
     */
    ...(LIVE_REQUESTED ? [{
      name: 'live',
      use: { ...devices['Desktop Chrome'] },
      testMatch: /live\.spec\.ts/,
      // Real builds share one worker pool and one Groq quota; running them in
      // parallel would have them fighting over both.
      fullyParallel: false,
      timeout: 600_000,
    }] : []),
  ],

  webServer: {
    // `--strictPort` on purpose: silently landing on 5174 is exactly the class
    // of failure the proxy was added to eliminate, and a passing suite on the
    // wrong port would hide it again.
    command: 'npm run dev -- --port 5173 --strictPort',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
