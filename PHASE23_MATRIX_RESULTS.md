# Phase 23 A2 — live matrix results

*Run 2026-08-29T12:29:05*

Pass criterion (fixed before any build ran): **>= 3 of 4** reach `done` or `done_with_context` with a downloadable ZIP, and every build that boots reports **0 5xx** from the runtime smoke test.

**Result: 1 of 1 rows reach a terminal state with a valid ZIP (matrix incomplete).**

> That count covers the FIRST half of the criterion only. The 0-5xx half is not in the API — the smoke-test line lives in the server log, and a row counted here can still have shipped every endpoint broken. Row 3 on 2026-08-28 did exactly that.

| Row | Shape | Status | Tokens | Duration | Files | ZIP |
|-----|-------|--------|--------|----------|-------|-----|
| 3 | complex / multi-entity | `done_with_context` | 87,551 | 729s | 24 | yes |

The smoke-test line is not in the API — read it from the server log:

```bash
grep -E "Runtime smoke test|failed to boot|no FastAPI entry point" server.log
```

## Per-row detail

### Row 3 — complex / multi-entity

- build_id: `e6a1da32-f018-446d-996d-c4d8c4d59402`
- status: `done_with_context` — Build completed with 3 unresolved verification issue(s) after automatic repair. See SESSION_CONTEXT.md.
- progress: 100.0%
- tokens by model: `{"openai/gpt-oss-20b": 22234, "openai/gpt-oss-120b": 65317}`
- download: HTTP 200, application/zip, 22,611 bytes
- expected to boot: yes
