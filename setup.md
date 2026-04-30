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

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cat > .env << EOF
GROQ_API_KEY=sk_...your_key...
LLM_PROVIDER=groq
OUTPUT_DIR=generated_projects
EOF

# Run migrations (if any)
python -m alembic upgrade head

# Start server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Step 3: Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

Access at: http://localhost:5173

## Step 4: Verify Installation

```bash
# Check backend health
curl http://localhost:8000/health

# Check frontend loads
# Visit http://localhost:5173 in browser
```

## 🧪 Running Tests

```bash
# Backend tests
cd backend
pytest tests/ -v

# Frontend tests
cd frontend
npm run test
```

## 📦 Building for Production

```bash
# Backend
cd backend
pip install gunicorn
gunicorn main:app -w 4 -b 0.0.0.0:8000

# Frontend
cd frontend
npm run build
# Output: dist/
```

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError` | Activate venv and `pip install -r requirements.txt` |
| Port 8000 in use | `lsof -i :8000` and kill process or use `--port 8001` |
| CORS errors | Check `allow_origins` in `api_platform/main.py` |
| npm install fails | Delete `node_modules` and `package-lock.json`, retry |

## 🔗 Useful Links

- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [React Docs](https://react.dev/)
- [Groq Console](https://console.groq.com/)
- [Tailwind CSS](https://tailwindcss.com/)