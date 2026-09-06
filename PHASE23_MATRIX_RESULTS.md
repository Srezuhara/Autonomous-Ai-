# Phase 23 A2 — live matrix results

*Run 2026-09-05T22:54:28*

Pass criterion (fixed before any build ran): **>= 3 of 4** reach `done` or `done_with_context` with a downloadable ZIP, and every build that boots reports **0 5xx** from the runtime smoke test.

**Result: 0 of 1 rows meet BOTH halves (matrix incomplete).** 0 shipped a valid ZIP.

> Both halves are now read from the API. The second one — did the artifact actually run — used to exist only as a line in the server log, so this file reported the first half and told the reader to grep for the rest. A row passes it when every check either verified the artifact or correctly did not apply, and at least one check executed it: four not-applicables are not evidence, and a check that never ran is a hole, not a pass. `generated_tests` is reported but does not decide a row — it asks whether the suite the build *ships* runs, not whether the thing built works, and a build can serve every route it declares while its generated tests do not collect.

| Row | Shape | Status | Verified | Tokens | Duration | Files | ZIP |
|-----|-------|--------|----------|--------|----------|-------|-----|
| 3 | complex / multi-entity | `unusable` | NO | 123,430 | 989s | 23 | yes |

## Per-row detail

### Row 3 — complex / multi-entity

- build_id: `9733027d-5026-4ced-b6f6-a76a7ed9024e`
- status: `unusable` — The build completed and the code is downloadable, but it does not run: the application starts but declares no routes, so it serves nothing. Every requested endpoint is missing.
- progress: 100.0%
- tokens by model: `{"openai/gpt-oss-20b": 51659, "openai/gpt-oss-120b": 71771}`
- download: HTTP 200, application/zip, 19,699 bytes
- expected to boot: yes
- build shape: web_api
- smoke: app loaded but declares no routes
- verified: **NO** — failed: runtime_smoke; for manual testing: generated_tests

| Check | Status | What it did |
|---|---|---|
| `runtime_smoke` | failed | the app at backend/main.py boots and declares 0 routes |
| `cli_smoke` | not_applicable | this project declares no command-line entry point |
| `web_assets` | not_applicable | this project ships no HTML page |
| `static_smoke` | not_applicable | this project ships no HTML page |
| `package_smoke` | not_applicable | this project is run, not imported; its own verifier covers it |
| `feature_coverage` | verified | 6/6 requested feature(s) have supporting code (0 route(s), 2 function(s) across web_api) |
| `schema_attr` | verified | 14 model(s) checked field-by-field (0 skipped as open) |
| `module_ref` | verified | 16 module(s) checked name-by-name (0 skipped as open) |
| `sql_schema` | not_applicable | this project creates no tables inline, so there is no schema here to check SQL against |
| `dead_events` | verified | 1 app(s) built with a lifespan, across 16 python file(s) |
| `generated_tests` | failed | pytest exit 1, 2 error, 21 failed, 8 passed |

- 🚨 the application starts but declares no routes, so it serves nothing. Every requested endpoint is missing.
- 🚨 the project's own test suite does not run: 2 of its tests error before executing
- 🚨 FAILED tests/test_main.py::test_lifespan_initializes_db - AssertionError: exp...
- 🚨 FAILED tests/test_products.py::test_create_product - assert 404 == 201
- 🚨 FAILED tests/test_products.py::test_get_product - assert 404 == 201
- 🚨 FAILED tests/test_products.py::test_update_product - assert 404 == 201
