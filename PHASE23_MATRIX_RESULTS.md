# Phase 23 A2 — live matrix results

*Run 2026-08-30T13:21:21*

Pass criterion (fixed before any build ran): **>= 3 of 4** reach `done` or `done_with_context` with a downloadable ZIP, and every build that boots reports **0 5xx** from the runtime smoke test.

**Result: 1 of 1 rows reach a terminal state with a valid ZIP (matrix incomplete).**

> That count covers the FIRST half of the criterion only. The 0-5xx half is not in the API — the smoke-test line lives in the server log, and a row counted here can still have shipped every endpoint broken. Row 3 on 2026-08-28 did exactly that.

| Row | Shape | Status | Tokens | Duration | Files | ZIP |
|-----|-------|--------|--------|----------|-------|-----|
| 3 | complex / multi-entity | `done_with_context` | 136,043 | 1142s | 25 | yes |

The smoke-test line is not in the API — read it from the server log:

```bash
grep -E "Runtime smoke test|failed to boot|no FastAPI entry point" server.log
```

## Per-row detail

### Row 3 — complex / multi-entity

- build_id: `90ee973f-1bf8-4855-889e-11aa35c418ce`
- status: `done_with_context` — Build completed with 1 unresolved verification issue(s) after automatic repair. See SESSION_CONTEXT.md.
- progress: 100.0%
- tokens by model: `{"openai/gpt-oss-20b": 97506, "openai/gpt-oss-120b": 38537}`
- download: HTTP 200, application/zip, 23,787 bytes
- expected to boot: yes
