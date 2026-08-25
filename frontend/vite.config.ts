import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

/**
 * The API is proxied rather than called cross-origin.
 *
 * Before this, the dev server called `http://localhost:8000` directly, which
 * made every request cross-origin and put the app at the mercy of the backend's
 * CORS allowlist. That allowlist contains `http://localhost:5173` and nothing
 * else — so starting Vite on any other port, or reaching it as `127.0.0.1`
 * rather than `localhost`, blocked every request and presented as "the frontend
 * is broken" with no clue pointing at the origin.
 *
 * Proxied, requests are same-origin. The port stops mattering, `127.0.0.1` and
 * `localhost` behave identically, and CORS is out of the picture entirely.
 */
const API_TARGET = process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000'

/** Every path the backend serves. Must stay in step with api_platform/main.py. */
const API_PREFIXES = ['/projects', '/jobs', '/stats', '/health', '/docs', '/openapi.json']

/**
 * Two of those prefixes are also client-side routes: `/stats` and
 * `/projects/{id}`. The backend now serves the built SPA from `frontend/dist`,
 * so proxying a browser *navigation* to one of them returned the production
 * index.html — whose hashed asset URLs do not exist on the dev server, giving
 * a blank page and a 404 for `/assets/index-*.js`.
 *
 * `bypass` returning the URL tells Vite to handle the request itself. It fires
 * only for requests that ask for HTML, so the app's own fetch() calls — which
 * do not — still reach the backend. Same Accept-header split the backend's SPA
 * middleware uses, applied from the other end.
 *
 * `/docs` is deliberately NOT in this set: Swagger UI is HTML that genuinely
 * belongs to the backend.
 */
const SPA_ROUTE_PREFIXES = new Set(['/projects', '/stats'])

function bypassHtmlNavigations(prefix: string) {
  if (!SPA_ROUTE_PREFIXES.has(prefix)) return undefined
  return (req: { url?: string; headers: Record<string, string | string[] | undefined> }) => {
    const accept = String(req.headers.accept ?? '')
    return accept.includes('text/html') ? req.url : undefined
  }
}

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      ...Object.fromEntries(
        API_PREFIXES.map(prefix => [prefix, {
          target: API_TARGET,
          changeOrigin: true,
          bypass: bypassHtmlNavigations(prefix),
        }])
      ),
      // The build progress socket. `ws: true` is what makes the proxy forward
      // the upgrade handshake instead of answering it as a normal request.
      '/ws': { target: API_TARGET, changeOrigin: true, ws: true },
    },
  },
})
