# Phase 23 A2 — live matrix results

*Run 2026-08-31T15:07:45*

Pass criterion (fixed before any build ran): **>= 3 of 4** reach `done` or `done_with_context` with a downloadable ZIP, and every build that boots reports **0 5xx** from the runtime smoke test.

**Result: 1 of 2 rows meet BOTH halves (matrix incomplete).** 1 shipped a valid ZIP.

> Both halves are now read from the API. The second one — did the artifact actually run — used to exist only as a line in the server log, so this file reported the first half and told the reader to grep for the rest. A row passes it when every check either verified the artifact or correctly did not apply, and at least one check executed it: four not-applicables are not evidence, and a check that never ran is a hole, not a pass. `generated_tests` is reported but does not decide a row — it asks whether the suite the build *ships* runs, not whether the thing built works, and a build can serve every route it declares while its generated tests do not collect.

| Row | Shape | Status | Verified | Tokens | Duration | Files | ZIP |
|-----|-------|--------|----------|--------|----------|-------|-----|
| 2 | medium FastAPI + JS frontend | `done_with_context` | yes | 173,307 | 1752s | 26 | yes *(earlier run)* |
| 3 | complex / multi-entity | `unusable` | NO | 174,213 | 1457s | 17 | yes |

## Per-row detail

### Row 3 — complex / multi-entity

- build_id: `3322017e-2f19-492f-94c2-3d02cd4d6b19`
- status: `unusable` — The build completed and the code is downloadable, but it does not run: the application does not start: SyntaxError: from __future__ imports must occur at the beginning of the file (models.py, line 10) (at backend/main.py:19 in <module>). Every endpoint is unreachable.
- progress: 100.0%
- tokens by model: `{"openai/gpt-oss-20b": 19031, "openai/gpt-oss-120b": 155182}`
- download: HTTP 200, application/zip, 18,608 bytes
- expected to boot: yes
- build shape: web_api
- smoke: app failed to load: SyntaxError: from __future__ imports must occur at the beginning of the file (models.py, line 10) (at backend/main.py:19 in <module>)
- verified: **NO** — failed: runtime_smoke; for manual testing: generated_tests

| Check | Status | What it did |
|---|---|---|
| `runtime_smoke` | failed | the app at backend/main.py raises while being imported |
| `cli_smoke` | not_applicable | this project declares no command-line entry point |
| `web_assets` | not_applicable | this project ships no HTML page |
| `static_smoke` | not_applicable | this project ships no HTML page |
| `package_smoke` | not_applicable | this project is run, not imported; its own verifier covers it |
| `feature_coverage` | verified | 6/6 requested feature(s) have supporting code (18 route(s), 24 function(s) across web_api) |
| `schema_attr` | not_applicable | this project declares no pydantic models |
| `generated_tests` | failed | pytest exit 2, 2 error |

- 🚨 the application does not start: SyntaxError: from __future__ imports must occur at the beginning of the file (models.py, line 10) (at backend/main.py:19 in <module>). Every endpoint is unreachable.
- 🚨 the project's own test suite does not run: 2 of its tests error before executing
- 🚨 ERROR tests/test_models.py
- 🚨 ERROR tests/test_routers.py
