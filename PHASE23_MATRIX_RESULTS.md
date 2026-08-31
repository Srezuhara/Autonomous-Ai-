# Phase 23 A2 — live matrix results

*Run 2026-08-31T11:31:10*

Pass criterion (fixed before any build ran): **>= 3 of 4** reach `done` or `done_with_context` with a downloadable ZIP, and every build that boots reports **0 5xx** from the runtime smoke test.

**Result: 1 of 1 rows meet BOTH halves (matrix incomplete).** 1 shipped a valid ZIP.

> Both halves are now read from the API. The second one — did the artifact actually run — used to exist only as a line in the server log, so this file reported the first half and told the reader to grep for the rest. A row passes it when every check either verified the artifact or correctly did not apply, and at least one check executed it: four not-applicables are not evidence, and a check that never ran is a hole, not a pass.

| Row | Shape | Status | Verified | Tokens | Duration | Files | ZIP |
|-----|-------|--------|----------|--------|----------|-------|-----|
| 2 | medium FastAPI + JS frontend | `done_with_context` | yes | 173,307 | 1752s | 26 | yes |

## Per-row detail

### Row 2 — medium FastAPI + JS frontend

- build_id: `e045ca2d-dfc9-4799-b199-a14fae4501b7`
- status: `done_with_context` — Build completed with 2 unresolved verification issue(s) after automatic repair. See SESSION_CONTEXT.md.
- progress: 100.0%
- tokens by model: `{"openai/gpt-oss-20b": 100673, "openai/gpt-oss-120b": 72634}`
- download: HTTP 200, application/zip, 23,911 bytes
- expected to boot: yes
- build shape: web_api+static_frontend
- smoke: 7/7 routes responded without a server error
- verified: **yes** — verified by runtime_smoke, web_assets, feature_coverage, schema_attr

| Check | Status | What it did |
|---|---|---|
| `runtime_smoke` | verified | 7/7 routes responded without a server error |
| `cli_smoke` | not_applicable | this project declares no command-line entry point |
| `web_assets` | verified | parsed 1 page(s), 3 frontend call(s) checked against 3 declared route(s) |
| `package_smoke` | not_applicable | this project is run, not imported; its own verifier covers it |
| `feature_coverage` | verified | 4/4 requested feature(s) have supporting code (7 route(s), 19 function(s) across web_api+static_frontend) |
| `schema_attr` | verified | 7 model(s) checked field-by-field (0 skipped as open) |

