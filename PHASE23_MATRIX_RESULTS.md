# Phase 23 A2 — live matrix results

*Run 2026-09-08T22:02:55*

Pass criterion (fixed before any build ran): **>= 3 of 4** reach `done` or `done_with_context` with a downloadable ZIP, and every build that boots reports **0 5xx** from the runtime smoke test.

**Result: 1 of 2 rows meet BOTH halves (matrix incomplete).** 1 shipped a valid ZIP.

> Both halves are now read from the API. The second one — did the artifact actually run — used to exist only as a line in the server log, so this file reported the first half and told the reader to grep for the rest. A row passes it when every check either verified the artifact or correctly did not apply, and at least one check executed it: four not-applicables are not evidence, and a check that never ran is a hole, not a pass. `generated_tests` is reported but does not decide a row — it asks whether the suite the build *ships* runs, not whether the thing built works, and a build can serve every route it declares while its generated tests do not collect.

| Row | Shape | Status | Verified | Tokens | Duration | Files | ZIP |
|-----|-------|--------|----------|--------|----------|-------|-----|
| 1 | simple FastAPI + SQLite CRUD | `done` | yes | 69,236 | 471s | 20 | yes *(earlier run)* |
| 2 | medium FastAPI + JS frontend | `unusable` | NO | 128,769 | 959s | 27 | yes |
| 3 | complex / multi-entity | `done_with_context` | yes | 128,676 | 965s | 29 | yes *(earlier run)* |
| 4 | non-FastAPI (CLI) | `unusable` | NO | 87,800 | 631s | 21 | yes *(earlier run)* |

> **Row 4's verdict belongs to the harness, not the build** (2026-09-08).
> `cli_smoke` ran the tool under a cp1252 stdout, so a non-breaking hyphen
> (U+2011) in its argparse description raised `UnicodeEncodeError` inside
> `print_help()` and the row was recorded "fails on `--help` (exit 1)". The same
> unmodified tool exits 0 under a UTF-8 stdout, every other check was verified
> or correctly not-applicable, and `generated_tests` **passed** — the first time
> in this phase. `cli_smoke` is fixed and now returns `verified` on that
> artifact, but a build record cannot be edited into a pass: the row is left as
> recorded and needs one clean re-run (~88K) to count. Row 3's line was restored
> by hand from `GET /projects/1134f369-…` after a merge defect, fixed in the
> same commit, dropped it.

## Per-row detail

### Row 2 — medium FastAPI + JS frontend

- build_id: `e1266aab-35dc-4250-b8f1-034b29df46af`
- status: `unusable` — The build completed and the code is downloadable, but it does not run: 9 of 9 endpoint(s) return a server error when called: GET /bookmarks → 500, POST /bookmarks → 500, GET /bookmarks/{bookmark_id} → 500, PUT /bookmarks/{bookmark_id} → 500, DELETE /bookmarks/{bookmark_id} → 500. These fail at request time, which the import check cannot see.
- progress: 100.0%
- tokens by model: `{"openai/gpt-oss-20b": 93250, "openai/gpt-oss-120b": 35519}`
- download: HTTP 200, application/zip, 27,421 bytes
- expected to boot: yes
- build shape: web_api+static_frontend
- smoke: 0/9 routes responded without a server error
- verified: **NO** — failed: runtime_smoke, static_smoke, call_arity; for manual testing: generated_tests

| Check | Status | What it did |
|---|---|---|
| `runtime_smoke` | failed | 0/9 routes responded without a server error |
| `cli_smoke` | not_applicable | this project declares no command-line entry point |
| `web_assets` | verified | parsed 2 page(s), 1 frontend call(s) checked against 4 declared route(s) |
| `static_smoke` | failed | served 2 page(s) over HTTP and fetched 3 local asset(s) |
| `package_smoke` | not_applicable | this project is run, not imported; its own verifier covers it |
| `feature_coverage` | verified | 4/4 requested feature(s) have supporting code (9 route(s), 27 function(s) across web_api+static_frontend) |
| `schema_attr` | verified | 7 model(s) checked field-by-field (0 skipped as open) |
| `module_ref` | verified | 12 module(s) checked name-by-name (0 skipped as open) |
| `sql_schema` | verified | 3 table(s) created, 3 queried |
| `dead_events` | verified | 1 app(s) built with a lifespan, across 12 python file(s) |
| `route_presence` | verified | 9 route(s) declared across 12 python file(s) |
| `call_arity` | failed | 11 call(s) checked against their definitions |
| `await_sync` | not_applicable | this project awaits nothing, so there is no coroutine mismatch to find |
| `generated_tests` | failed | pytest exit 2, 3 error |

- 🚨 9 of 9 endpoint(s) return a server error when called: GET /bookmarks → 500, POST /bookmarks → 500, GET /bookmarks/{bookmark_id} → 500, PUT /bookmarks/{bookmark_id} → 500, DELETE /bookmarks/{bookmark_id} → 500. These fail at request time, which the import check cannot see.
- 🚨 bookmark_manager_e1266aab/frontend/templates/form.html loads `/static/styles.css`, which is not served (HTTP 404) because it is not in the project — `web_assets` names it in full
- 🚨 bookmark_manager_e1266aab/frontend/templates/index.html loads `/static/scripts.js`, which is not served (HTTP 404) because it is not in the project — `web_assets` names it in full
- 🚨 bookmark_manager_e1266aab/frontend/templates/index.html loads `/static/styles.css`, which is not served (HTTP 404) because it is not in the project — `web_assets` names it in full
- 🚨 `services.delete_tag(...)` at backend/routes.py:118 passes 2 positional argument(s) to a function that takes 1 — `def delete_tag(tag_id: int)` in services.py. The call raises TypeError every time it runs. Fix the CALL to match the definition, or the definition to match its callers.
- 🚨 the project's own test suite does not run: 3 of its tests error before executing
- 🚨 ERROR tests/test_api.py - RuntimeError: Directory 'C:\Users\KIIT0001\AppData\...
- 🚨 ERROR tests/test_main.py - RuntimeError: Directory 'C:\Users\KIIT0001\AppData...
- 🚨 ERROR tests/test_routes.py - RuntimeError: Directory 'C:\Users\KIIT0001\AppDa...
