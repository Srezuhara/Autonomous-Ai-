# Phase 23 A2 — live matrix results

*Run 2026-08-28T12:39:20*

Pass criterion (fixed before any build ran): **>= 3 of 4** reach `done` or `done_with_context` with a downloadable ZIP, and every build that boots reports **0 5xx** from the runtime smoke test.

**Result: 2 of 2 rows pass (matrix incomplete).**

| Row | Shape | Status | Tokens | Duration | Files | ZIP |
|-----|-------|--------|--------|----------|-------|-----|
| 2 | medium FastAPI + JS frontend | `done_with_context` | 171,914 | 1429s | 20 | yes |
| 3 | complex / multi-entity | `done_with_context` | 131,848 | 1342s | 22 | yes |

The smoke-test line is not in the API — read it from the server log:

```bash
grep -E "Runtime smoke test|failed to boot|no FastAPI entry point" server.log
```

## Per-row detail

### Row 2 — medium FastAPI + JS frontend

- build_id: `2323e41f-1f5c-447a-80b7-db877e4f791b`
- status: `done_with_context` — Build completed with 3 unresolved verification issue(s) after automatic repair. See SESSION_CONTEXT.md.
- progress: 100.0%
- tokens by model: `{"openai/gpt-oss-20b": 128100, "openai/gpt-oss-120b": 43814}`
- download: HTTP 200, application/zip, 20,247 bytes
- expected to boot: yes

### Row 3 — complex / multi-entity

- build_id: `e9eac7be-6239-4ed3-9da9-ef1955714451`
- status: `done_with_context` — LLM daily quota exhausted during step 8 (90% complete). Generated files packaged with SESSION_CONTEXT.md.
- progress: 90.0%
- tokens by model: `{"openai/gpt-oss-120b": 131848}`
- download: HTTP 200, application/zip, 19,146 bytes
- expected to boot: yes
