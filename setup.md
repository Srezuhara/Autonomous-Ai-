# Development Setup Guide

## Prerequisites

- Python 3.10+
- Node.js 18+
- Git
- Groq API key (free at https://console.groq.com)

## Step 1: Clone Repository

```bash
git clone https://github.com/YOUR_USERNAME/ai-app-builder.git
cd ai-app-builder
```

## Step 2: Backend Setup

The backend lives at the repository root — there is no `backend/` directory.

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cat > .env << EOF
GROQ_API_KEY=sk_...your_key...
LLM_PROVIDER=groq
OUTPUT_DIR=generated_projects
EOF
```

The database is SQLite and initialises itself on first start — there are no
migrations to run.

```bash
# Start the server. Use the venv's interpreter: the system Python is missing
# `rich` and dies on import before the server comes up.
venv/Scripts/python.exe start_server.py      # Windows
./venv/bin/python start_server.py            # macOS / Linux
```

Serves on http://localhost:8000 — API docs at `/docs`.

## Step 3: Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

Access at **http://localhost:5173**.

> **Use `localhost`, not `127.0.0.1`.** Vite binds to whatever `localhost`
> resolves to, which on many systems is IPv6 `::1` only — so
> `http://127.0.0.1:5173` is refused at the socket, before any app code runs.
> If you need the literal IPv4 address, start with `npm run dev -- --host`
> (which also exposes the server on your network).

The dev server proxies `/projects`, `/jobs`, `/stats`, `/health`, `/docs` and
`/ws` to the backend on port 8000, so API requests are same-origin and CORS
never enters the picture. See `frontend/vite.config.ts`.

## Step 3b: One-command mode (optional)

Build the frontend once and the backend serves it from the same origin — no
second port, no proxy:

```bash
cd frontend && npm run build && cd ..
venv/Scripts/python.exe start_server.py
```

The whole product is then at http://localhost:8000. With no `frontend/dist`
present the backend behaves exactly as before, serving the API only.

## Step 4: Verify Installation

```bash
# Check backend health
curl http://localhost:8000/health

# Check frontend loads
# Visit http://localhost:5173 in a browser
```

## 🧪 Running Tests

### Backend

There is no `pytest` suite. The backend is covered by four standalone scripts
at the repository root, each run directly:

```bash
venv/Scripts/python.exe test_phase17.py                   # needs the server running
venv/Scripts/python.exe test_phase21.py
venv/Scripts/python.exe test_phase22.py
venv/Scripts/python.exe test_groq_rate_limit_handling.py
```

`test_phase17.py` exercises the live HTTP API, so start the server first. The
other three are self-contained.

### Frontend

```bash
cd frontend

npm run typecheck      # tsc -b across app, node and test projects
npm run lint           # eslint
npm run test           # Vitest + Testing Library (component + unit)
npm run test:coverage  # the same, with a coverage report
npm run test:e2e       # Playwright + axe — needs BOTH servers running
```

`npm run test:e2e` starts the Vite dev server itself but **not** the backend —
that owns a database and a worker pool, so you start it deliberately:

```bash
# terminal 1
venv/Scripts/python.exe start_server.py
# terminal 2
cd frontend && npm run test:e2e
```

One E2E test POSTs a real build and therefore spends real LLM quota. It is
skipped by default; run it explicitly with:

```bash
E2E_LIVE_BUILD=1 npm run test:e2e
```

## 📦 Building for Production

```bash
# Frontend
cd frontend
npm run build          # output: frontend/dist/

# Backend (serves the built frontend from the same origin)
pip install gunicorn
gunicorn api_platform.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000
```

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: rich` | You ran system Python. Use `venv/Scripts/python.exe`. |
| `127.0.0.1:5173` refuses to connect | Vite is bound to IPv6 only. Use `localhost:5173`, or start with `--host`. |
| Port 8000 in use | `lsof -i :8000` (Windows: `netstat -ano \| findstr :8000`) and kill it, or run on another port. |
| CORS errors | Shouldn't happen in dev — the Vite proxy makes requests same-origin. If you bypassed the proxy, check `allow_origins` in `api_platform/main.py`. |
| `/stats` shows a blank page in dev | The proxy must bypass HTML navigations for SPA-colliding paths; see `SPA_ROUTE_PREFIXES` in `frontend/vite.config.ts`. |
| npm install fails | Delete `node_modules` and `package-lock.json`, retry. |
| `pip-audit` reports CVEs | Check whether the package is actually imported. `chromadb` and `langchain` are declared in requirements.txt but never used, and they pull in torch / pillow / nltk / gitpython. Every request-path package is clean. |
| E2E fails with connection errors | The backend is not running. See "Running Tests" above. |

## 🔗 Useful Links

- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [React Docs](https://react.dev/)
- [Groq Console](https://console.groq.com/)
- [Vitest](https://vitest.dev/) · [Playwright](https://playwright.dev/)
