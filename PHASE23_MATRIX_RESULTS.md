# Phase 23 A2 — live matrix results

*Run 2026-09-06T20:10:25*

Pass criterion (fixed before any build ran): **>= 3 of 4** reach `done` or `done_with_context` with a downloadable ZIP, and every build that boots reports **0 5xx** from the runtime smoke test.

**Result: 0 of 1 rows meet BOTH halves (matrix incomplete).** 0 shipped a valid ZIP.

> Both halves are now read from the API. The second one — did the artifact actually run — used to exist only as a line in the server log, so this file reported the first half and told the reader to grep for the rest. A row passes it when every check either verified the artifact or correctly did not apply, and at least one check executed it: four not-applicables are not evidence, and a check that never ran is a hole, not a pass. `generated_tests` is reported but does not decide a row — it asks whether the suite the build *ships* runs, not whether the thing built works, and a build can serve every route it declares while its generated tests do not collect.

| Row | Shape | Status | Verified | Tokens | Duration | Files | ZIP |
|-----|-------|--------|----------|--------|----------|-------|-----|
| 3 | complex / multi-entity | `unusable` | NO | 96,304 | 704s | 23 | yes |

## Per-row detail

### Row 3 — complex / multi-entity

- build_id: `51d80952-6c89-455d-8e0b-aeba4d65e8c9`
- status: `unusable` — The build completed and the code is downloadable, but it does not run: the application starts but declares no routes, so it serves nothing. Every requested endpoint is missing.; the application declares no routes at all, so it serves nothing and every requested endpoint is missing. `backend/main.py` builds a router and declares nothing on it. Add the `@router.get/post/put/delete` handlers.; feature_coverage did not run, so this build is unverified: this project is a web API that declares no rout
- progress: 100.0%
- tokens by model: `{"openai/gpt-oss-20b": 45120, "openai/gpt-oss-120b": 51184}`
- download: HTTP 200, application/zip, 23,985 bytes
- expected to boot: yes
- build shape: web_api
- smoke: app loaded but declares no routes
- verified: **NO** — failed: runtime_smoke, route_presence; for manual testing: generated_tests

| Check | Status | What it did |
|---|---|---|
| `runtime_smoke` | failed | the app at backend/main.py boots and declares 0 routes |
| `cli_smoke` | not_applicable | this project declares no command-line entry point |
| `web_assets` | not_applicable | this project ships no HTML page |
| `static_smoke` | not_applicable | this project ships no HTML page |
| `package_smoke` | not_applicable | this project is run, not imported; its own verifier covers it |
| `feature_coverage` | not_run | this project is a web API that declares no routes at all, so there is nothing for its requested features to be covered BY — matching words against it would prove nothing |
| `schema_attr` | verified | 15 model(s) checked field-by-field (0 skipped as open) |
| `module_ref` | verified | 16 module(s) checked name-by-name (1 skipped as open) |
| `sql_schema` | not_applicable | this project creates no tables inline, so there is no schema here to check SQL against |
| `dead_events` | verified | 1 app(s) built with a lifespan, across 17 python file(s) |
| `route_presence` | failed | 0 route(s) declared across 17 python file(s) |
| `generated_tests` | failed | pytest exit 1, 8 error, 16 failed, 9 passed, 2 skipped |

- 🚨 the application starts but declares no routes, so it serves nothing. Every requested endpoint is missing.
- 🚨 the application declares no routes at all, so it serves nothing and every requested endpoint is missing. `backend/main.py` builds a router and declares nothing on it. Add the `@router.get/post/put/delete` handlers.
- 🚨 the project's own test suite does not run: 8 of its tests error before executing
- 🚨 FAILED tests/test_models.py::test_supplier_product_relationship - AttributeEr...
- 🚨 FAILED tests/test_products.py::test_create_product - assert 404 == 201
- 🚨 FAILED tests/test_products.py::test_get_products - assert 404 == 200
- 🚨 FAILED tests/test_products.py::test_get_product_by_id - TypeError: string ind...
