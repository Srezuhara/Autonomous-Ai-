# AI App Builder — Stage 1, Phase 1 & 2

> CLI AI system that generates full applications from a prompt.

---

## Project Structure

```
ai_app_builder/
├── agents/             # AI agents (planner, coder, reviewer…)
├── tools/              # File writer, code executor, installer
├── memory/             # ChromaDB vector memory
├── prompts/            # System prompt templates
├── generated_projects/ # All AI-generated apps land here
├── main.py             # CLI entry point
├── config.py           # Central config (reads .env)
├── llm_client.py       # Unified Groq + Ollama interface
├── requirements.txt
└── .env.example
```

---

## Setup (do this once)

### 1 — Clone / create folder
```bash
cd ai_app_builder
```

### 2 — Python virtual environment
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
```

### 3 — Install dependencies
```bash
pip install -r requirements.txt
```

### 4 — Configure environment
```bash
cp .env.example .env
# Open .env and add your GROQ_API_KEY
# Get one free at https://console.groq.com
```

### 5 — (Optional) Install local Ollama model for fallback
```bash
# Install Ollama: https://ollama.com
ollama pull deepseek-coder:6.7b
```

---

## Verify Setup

```bash
# Check config loads correctly
python main.py

# Smoke-test the LLM client (calls the real API)
python llm_client.py
```

Expected output:
```
=== Text test ===
Hello! How can I assist you today?

=== Code test ===
def fibonacci(n):
    ...
```

---

## LLM Provider Modes

Set `LLM_PROVIDER` in your `.env`:

| Value    | Behaviour                              |
|----------|----------------------------------------|
| `groq`   | Groq only (fast, requires API key)     |
| `ollama` | Ollama only (local, no key needed)     |
| `both`   | Groq first → falls back to Ollama      |

---

## What's Next

| Phase | Description |
|-------|-------------|
| ✅ 1 | Environment setup |
| ✅ 2 | Project structure |
| ✅ 3 | LLM interface (llm_client.py) |
| ⬜ 4 | Tool system (file writer, code executor) |
| ⬜ 5 | Planning agents |
| ⬜ 6 | Code generation agents |
| ⬜ 7 | Autonomous debugging loop |
| ⬜ 8 | Testing & review agents |
| ⬜ 9 | Documentation agent |
| ⬜ 10 | Rich CLI interface |
