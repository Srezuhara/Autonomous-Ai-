# Phase 23 A2 — live matrix results

*Run 2026-08-30T19:53:30*

Pass criterion (fixed before any build ran): **>= 3 of 4** reach `done` or `done_with_context` with a downloadable ZIP, and every build that boots reports **0 5xx** from the runtime smoke test.

**Result: 1 of 1 rows reach a terminal state with a valid ZIP (matrix incomplete).**

> That count covers the FIRST half of the criterion only. The 0-5xx half is not in the API — the smoke-test line lives in the server log, and a row counted here can still have shipped every endpoint broken. Row 3 on 2026-08-28 did exactly that.

| Row | Shape | Status | Tokens | Duration | Files | ZIP |
|-----|-------|--------|--------|----------|-------|-----|
| 4 | non-FastAPI (CLI) | `done` | 109,206 | 932s | 20 | yes |

The smoke-test line is not in the API — read it from the server log:

```bash
grep -E "Runtime smoke test|failed to boot|no FastAPI entry point" server.log
```

## Per-row detail

### Row 4 — non-FastAPI (CLI)

- build_id: `912f9b22-896d-4117-8723-4b72f56bb25b`
- status: `done`
- progress: 100.0%
- tokens by model: `{"openai/gpt-oss-20b": 49729, "openai/gpt-oss-120b": 59477}`
- download: HTTP 200, application/zip, 14,283 bytes
- expected to boot: no (smoke test must skip cleanly)
