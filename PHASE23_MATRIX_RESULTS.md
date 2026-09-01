# Phase 23 A2 — live matrix results

*Run 2026-09-01T11:45:10*

Pass criterion (fixed before any build ran): **>= 3 of 4** reach `done` or `done_with_context` with a downloadable ZIP, and every build that boots reports **0 5xx** from the runtime smoke test.

**Result: 0 of 1 rows meet BOTH halves (matrix incomplete).** 0 shipped a valid ZIP.

> Both halves are now read from the API. The second one — did the artifact actually run — used to exist only as a line in the server log, so this file reported the first half and told the reader to grep for the rest. A row passes it when every check either verified the artifact or correctly did not apply, and at least one check executed it: four not-applicables are not evidence, and a check that never ran is a hole, not a pass. `generated_tests` is reported but does not decide a row — it asks whether the suite the build *ships* runs, not whether the thing built works, and a build can serve every route it declares while its generated tests do not collect.

| Row | Shape | Status | Verified | Tokens | Duration | Files | ZIP |
|-----|-------|--------|----------|--------|----------|-------|-----|
| 3 | complex / multi-entity | `unusable` | NO | 222,068 | 1863s | 27 | yes |

## Per-row detail

### Row 3 — complex / multi-entity

- build_id: `885804e4-a623-4e06-9d4c-2aa9c67c4c18`
- status: `unusable` — The build completed and the code is downloadable, but it does not run: the application does not start: NameError: name 'router' is not defined (at app/main.py:36 in <module>). Every endpoint is unreachable.
- progress: 100.0%
- tokens by model: `{"openai/gpt-oss-20b": 157242, "openai/gpt-oss-120b": 64826}`
- download: HTTP 200, application/zip, 26,080 bytes
- expected to boot: yes
- build shape: web_api
- smoke: app failed to load: NameError: name 'router' is not defined (at app/main.py:36 in <module>)
- verified: **NO** — failed: runtime_smoke, module_ref; for manual testing: generated_tests

| Check | Status | What it did |
|---|---|---|
| `runtime_smoke` | failed | the app at app/main.py raises while being imported |
| `cli_smoke` | not_applicable | this project declares no command-line entry point |
| `web_assets` | not_applicable | this project ships no HTML page |
| `static_smoke` | not_applicable | this project ships no HTML page |
| `package_smoke` | not_applicable | this project is run, not imported; its own verifier covers it |
| `feature_coverage` | verified | 6/6 requested feature(s) have supporting code (22 route(s), 27 function(s) across web_api) |
| `schema_attr` | verified | 14 model(s) checked field-by-field (0 skipped as open) |
| `module_ref` | failed | 17 module(s) checked name-by-name (4 skipped as open); 1 of the finding(s) are in test modules |
| `generated_tests` | failed | pytest exit 2, 5 error |

- 🚨 the application does not start: NameError: name 'router' is not defined (at app/main.py:36 in <module>). Every endpoint is unreachable.
- 🚨 `app.main.router` is read at line 9: `app.main` defines allow_origins, app, lifespan, and no `router`. This raises when the test module is imported, so this test cannot run (the application itself is unaffected). Add `router` to `app.main` — do NOT delete the reference or point it at a different name, which silently changes what this code does instead of fixing it.
- 🚨 the project's own test suite does not run: 5 of its tests error before executing
- 🚨 ERROR tests/test_products.py - NameError: name 'router' is not defined
- 🚨 ERROR tests/test_stock_movements.py - NameError: name 'router' is not defined
- 🚨 ERROR tests/test_suppliers.py - NameError: name 'router' is not defined
- 🚨 ERROR tests/test_test_suppliers.py - TypeError: 'mappingproxy' object does no...
