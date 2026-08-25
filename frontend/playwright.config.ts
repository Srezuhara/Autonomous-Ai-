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
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
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
