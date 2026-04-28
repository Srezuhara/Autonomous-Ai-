# AI App Builder — Project Context & Progress Log
Last Updated: 2026-03-08

---

## System Specs
- RAM: 16GB (15.7GB usable)
- CPU: 12th Gen Intel Core i7-1255U (1.70 GHz)
- No dedicated GPU — Ollama runs on CPU
- OS: Windows
- Editor: VS Code

---

## Project Location
C:\programes\comppython\Aiautonomous\

## Project Structure
```
Aiautonomous/
├── agents/               # AI agents (planner, coder, reviewer)
├── tools/                # File writer, code executor, installer
├── memory/               # ChromaDB vector memory
├── prompts/              # System prompt templates
├── generated_projects/   # All AI-generated apps land here
├── venv/                 # Python virtual environment ✅
├── main.py               # CLI entry point
├── config.py             # Central config (reads .env)
├── llm_client.py         # Unified Groq + Ollama interface
├── requirements.txt      # All dependencies
├── .env                  # Local config (never commit this)
└── README.md
```

---

## Environment
- Python: 3.11
- Venv: ✅ Active (select via VS Code "Python: Select Interpreter")
- Dependencies: ✅ Installed via `pip install -r requirements.txt`
- VS Code settings: terminal auto-activates venv

---

## .env Configuration
```env
LLM_PROVIDER=both

GROQ_API_KEY=<your_key>          # Get new one at console.groq.com
GROQ_MODEL=llama-3.3-70b-versatile

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5-coder:7b-instruct-q4_K_M

LOG_LEVEL=WARNING
OUTPUT_DIR=generated_projects
```

---

## LLM Setup
### Groq ✅ Working
- Model: llama-3.3-70b-versatile
- Note: llama3-70b-8192 is DECOMMISSIONED — do not use
- Rate limit: 1000 req/min, 12000 tokens/min (free tier)

### Ollama ⏳ Pending
- Install: OllamaSetup.exe (already in project folder)
- Model to pull: qwen2.5-coder:7b-instruct-q4_K_M (~4.5GB)
- Command: `ollama pull qwen2.5-coder:7b-instruct-q4_K_M`
- Speed expectation: 3-8 tokens/sec on CPU (normal)
- To test: set LLM_PROVIDER=ollama in .env, run python llm_client.py

---

## Issues Resolved
| Issue | Fix |
|-------|-----|
| .env not found | Used `Path(__file__).parent / ".env"` in config.py |
| env.example not renamed | Run `copy env.example .env` in terminal |
| llama3-70b-8192 decommissioned | Changed to llama-3.3-70b-versatile |
| OLLAMA_MODEL typo (double key) | Fixed to single `OLLAMA_MODEL=...` |
| Ollama 404 error | Model not pulled yet — run ollama pull |
| venv not showing in VS Code | Created venv first with `python -m venv venv` |

---

## Phase Progress

### STAGE 1 — MVP AI Engine
| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Environment setup | ✅ Complete |
| 2 | Project structure | ✅ Complete |
| 3 | LLM interface (llm_client.py) | ✅ Complete |
| 4 | Tool system (file writer, executor) | 🔄 Starting now |
| 5 | Planning agents | ⬜ Pending |
| 6 | Code generation agents | ⬜ Pending |
| 7 | Autonomous debugging loop | ⬜ Pending |
| 8 | Testing & review agents | ⬜ Pending |
| 9 | Documentation agent | ⬜ Pending |
| 10 | Rich CLI interface | ⬜ Pending |

### STAGE 2 — Platform Backend
| Phase | Description | Status |
|-------|-------------|--------|
| 11 | FastAPI backend | ⬜ Pending |
| 12 | Database (SQLite/Supabase) | ⬜ Pending |
| 13 | Background task queue | ⬜ Pending |
| 14 | Project storage | ⬜ Pending |

### STAGE 3 — SaaS Platform
| Phase | Description | Status |
|-------|-------------|--------|
| 15 | React frontend | ⬜ Pending |
| 16 | Authentication (JWT) | ⬜ Pending |
| 17 | Real-time WebSocket updates | ⬜ Pending |
| 18 | Live app preview | ⬜ Pending |
| 19 | AI memory (ChromaDB) | ⬜ Pending |
| 20 | UI improvement agent | ⬜ Pending |
| 21 | Deployment | ⬜ Pending |

---

## Key Commands
```bash
# Activate venv (auto in VS Code)
venv\Scripts\activate

# Run app
python main.py

# Test LLM connection
python llm_client.py

# Check Ollama models
ollama list

# Pull local model
ollama pull qwen2.5-coder:7b-instruct-q4_K_M

# Install dependencies
pip install -r requirements.txt
```

---

## Phase 4 — Tool System (Starting Next)
Will create:
- tools/file_writer.py  — create_file(), create_folder(), write_json()
- tools/code_executor.py — run_python(), run_command()
- tools/dependency_installer.py — pip_install(), npm_install()

These tools give AI agents the ability to physically create
files and run code on the machine.
