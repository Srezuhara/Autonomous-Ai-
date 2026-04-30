# AI App Builder

An intelligent full-stack application generator that uses AI agents to automatically design, develop, test, and deploy web applications from natural language prompts.

## 🚀 Features

- **Multi-Agent Pipeline:** Intent analysis, planning, architecture design, code generation
- **Full-Stack Generation:** FastAPI backend + React frontend with Tailwind CSS
- **Quality Assurance:** Autonomous debugging, code review, and testing
- **Real-Time Progress:** WebSocket updates and build status tracking
- **Project Management:** ZIP downloads, statistics, and project history

## 📦 Tech Stack

**Backend:**
- FastAPI (Python 3.10+)
- SQLite with SQLAlchemy
- LLM Integration (Groq API)

**Frontend:**
- React 19 with TypeScript
- Tailwind CSS 4
- React Router v7
- Vite (build tool)

## 🛠️ Setup

### Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Groq API key

# Start server
uvicorn main:app --reload
```

### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

Server: `http://localhost:8000`
Frontend: `http://localhost:5173`

## 📚 Project Structure

## 🔑 Environment Variables

Create `.env`:

## 🔄 Build Pipeline (9 Steps)

1. Intent Analysis → Parse user requirements
2. Planning → Create build roadmap
3. Architecture → Design folder structure
4. Backend Dev → Generate FastAPI code
5. Frontend Dev → Generate React code
6. Debugging → Fix import errors
7. Review → Code quality check
8. Testing → Generate & run pytest
9. Documentation → README generation

## 📡 API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST   | `/projects/` | Start new build |
| GET    | `/projects/` | List all projects |
| GET    | `/projects/{id}` | Project details |
| GET    | `/jobs/{id}/status` | Build progress |
| WS     | `/ws/jobs/{id}` | Real-time updates |
| GET    | `/projects/{id}/download` | ZIP download |
| GET    | `/stats` | Platform statistics |

## 📝 License

MIT

## 🤝 Contributing

Contributions welcome! Please follow the coding standards and include tests.

---

