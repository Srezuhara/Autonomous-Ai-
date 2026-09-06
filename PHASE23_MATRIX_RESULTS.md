# Phase 23 A2 — live matrix results

*Run 2026-09-06T21:09:33*

Pass criterion (fixed before any build ran): **>= 3 of 4** reach `done` or `done_with_context` with a downloadable ZIP, and every build that boots reports **0 5xx** from the runtime smoke test.

**Result: 0 of 1 rows meet BOTH halves (matrix incomplete).** 1 shipped a valid ZIP.

> Both halves are now read from the API. The second one — did the artifact actually run — used to exist only as a line in the server log, so this file reported the first half and told the reader to grep for the rest. A row passes it when every check either verified the artifact or correctly did not apply, and at least one check executed it: four not-applicables are not evidence, and a check that never ran is a hole, not a pass. `generated_tests` is reported but does not decide a row — it asks whether the suite the build *ships* runs, not whether the thing built works, and a build can serve every route it declares while its generated tests do not collect.

| Row | Shape | Status | Verified | Tokens | Duration | Files | ZIP |
|-----|-------|--------|----------|--------|----------|-------|-----|
| 3 | complex / multi-entity | `done_with_context` | NO | 140,637 | 1095s | 23 | yes |

## Per-row detail

### Row 3 — complex / multi-entity

- build_id: `78097ea4-2a16-415b-8f86-8b4945da2fc5`
- status: `done_with_context` — Build completed with 11 unresolved verification issue(s) after automatic repair. See SESSION_CONTEXT.md.
- progress: 100.0%
- tokens by model: `{"openai/gpt-oss-20b": 74639, "openai/gpt-oss-120b": 65998}`
- download: HTTP 200, application/zip, 24,301 bytes
- expected to boot: yes
- build shape: web_api
- smoke: 3/22 routes responded without a server error
- verified: **NO** — failed: runtime_smoke; for manual testing: generated_tests

| Check | Status | What it did |
|---|---|---|
| `runtime_smoke` | failed | 3/22 routes responded without a server error |
| `cli_smoke` | not_applicable | this project declares no command-line entry point |
| `web_assets` | not_applicable | this project ships no HTML page |
| `static_smoke` | not_applicable | this project ships no HTML page |
| `package_smoke` | not_applicable | this project is run, not imported; its own verifier covers it |
| `feature_coverage` | verified | 6/6 requested feature(s) have supporting code (22 route(s), 53 function(s) across web_api) |
| `schema_attr` | verified | 11 model(s) checked field-by-field (0 skipped as open) |
| `module_ref` | verified | 15 module(s) checked name-by-name (0 skipped as open) |
| `sql_schema` | verified | 4 table(s) created, 4 queried |
| `dead_events` | verified | 1 app(s) built with a lifespan, across 15 python file(s) |
| `route_presence` | verified | 22 route(s) declared across 15 python file(s) |
| `generated_tests` | failed | pytest exit 1, 18 failed, 6 passed |

- 🚨 19 of 22 endpoint(s) return a server error when called: POST /suppliers/ → 500, GET /suppliers/ → 500, GET /suppliers/{supplier_id} → 500, PUT /suppliers/{supplier_id} → 500, DELETE /suppliers/{supplier_id} → 500. These fail at request time, which the import check cannot see.
- 🚨 the project's own test suite fails: 18 failed, 6 passed
- 🚨 FAILED tests/test_main.py::test_list_suppliers_returns_ok - sqlite3.Operation...
- 🚨 FAILED tests/test_main.py::test_get_supplier_not_found - TypeError: object No...
- 🚨 FAILED tests/test_main.py::test_create_supplier_success - TypeError: object d...
- 🚨 FAILED tests/test_products.py::test_product_crud - AttributeError: 'async_gen...
