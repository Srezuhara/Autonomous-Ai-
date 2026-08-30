# Phase 23 A2 — live matrix results

*Run 2026-08-30T13:38:34*

Pass criterion (fixed before any build ran): **>= 3 of 4** reach `done` or `done_with_context` with a downloadable ZIP, and every build that boots reports **0 5xx** from the runtime smoke test.

**Result: 2 of 2 rows reach a terminal state with a valid ZIP (matrix incomplete).**

> That count covers the FIRST half of the criterion only. The 0-5xx half is not in the API — the smoke-test line lives in the server log, and a row counted here can still have shipped every endpoint broken. Row 3 on 2026-08-28 did exactly that.

| Row | Shape | Status | Tokens | Duration | Files | ZIP |
|-----|-------|--------|--------|----------|-------|-----|
| 3 | complex / multi-entity | `done_with_context` | 136,043 | 1142s | 25 | yes *(earlier run)* |
| 4 | non-FastAPI (CLI) | `done_with_context` | 105,999 | 882s | 23 | yes |

The smoke-test line is not in the API — read it from the server log:

```bash
grep -E "Runtime smoke test|failed to boot|no FastAPI entry point" server.log
```

## Per-row detail

### Row 4 — non-FastAPI (CLI)

- build_id: `ab57297e-3ac6-407b-b56f-8aa294e82b2c`
- status: `done_with_context` — Build completed with 2 unresolved verification issue(s) after automatic repair. See SESSION_CONTEXT.md.
- progress: 100.0%
- tokens by model: `{"openai/gpt-oss-20b": 66344, "openai/gpt-oss-120b": 39655}`
- download: HTTP 200, application/zip, 22,189 bytes
- expected to boot: no (smoke test must skip cleanly)
