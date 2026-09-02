# Phase 23 A2 — live matrix results

*Run 2026-09-02T23:07:13*

Pass criterion (fixed before any build ran): **>= 3 of 4** reach `done` or `done_with_context` with a downloadable ZIP, and every build that boots reports **0 5xx** from the runtime smoke test.

**Result: 0 of 1 rows meet BOTH halves (matrix incomplete).** 1 shipped a valid ZIP.

> Both halves are now read from the API. The second one — did the artifact actually run — used to exist only as a line in the server log, so this file reported the first half and told the reader to grep for the rest. A row passes it when every check either verified the artifact or correctly did not apply, and at least one check executed it: four not-applicables are not evidence, and a check that never ran is a hole, not a pass. `generated_tests` is reported but does not decide a row — it asks whether the suite the build *ships* runs, not whether the thing built works, and a build can serve every route it declares while its generated tests do not collect.

| Row | Shape | Status | Verified | Tokens | Duration | Files | ZIP |
|-----|-------|--------|----------|--------|----------|-------|-----|
| 3 | complex / multi-entity | `done_with_context` | NO | 117,191 | 997s | 23 | yes |

## Per-row detail

### Row 3 — complex / multi-entity

- build_id: `d1b98d57-023a-4bfa-af2a-48250d31bfa0`
- status: `done_with_context` — Build completed with 34 unresolved verification issue(s) after automatic repair. See SESSION_CONTEXT.md.
- progress: 100.0%
- tokens by model: `{"openai/gpt-oss-20b": 59146, "openai/gpt-oss-120b": 58045}`
- download: HTTP 200, application/zip, 23,630 bytes
- expected to boot: yes
- build shape: web_api
- smoke: 1/22 routes responded without a server error
- verified: **NO** — failed: runtime_smoke, module_ref; for manual testing: generated_tests

| Check | Status | What it did |
|---|---|---|
| `runtime_smoke` | failed | 1/22 routes responded without a server error |
| `cli_smoke` | not_applicable | this project declares no command-line entry point |
| `web_assets` | not_applicable | this project ships no HTML page |
| `static_smoke` | not_applicable | this project ships no HTML page |
| `package_smoke` | not_applicable | this project is run, not imported; its own verifier covers it |
| `feature_coverage` | verified | 6/6 requested feature(s) have supporting code (22 route(s), 29 function(s) across web_api) |
| `schema_attr` | verified | 19 model(s) checked field-by-field (0 skipped as open) |
| `module_ref` | failed | 15 module(s) checked name-by-name (0 skipped as open) |
| `generated_tests` | failed | pytest exit 1, 5 error, 19 failed, 6 passed |

- 🚨 21 of 22 endpoint(s) return a server error when called: GET /suppliers → 500, POST /suppliers → 500, GET /suppliers/{supplier_id} → 500, PUT /suppliers/{supplier_id} → 500, DELETE /suppliers/{supplier_id} → 500. These fail at request time, which the import check cannot see.
- 🚨 `backend.services.init_db` is read at line 31: `backend.services` defines DB_PATH, get_stock_level, get_stock_levels_by_warehouse, low_stock_report, and no `init_db`. This raises on every call that reaches it. Add `init_db` to `backend.services` — do NOT delete the reference or point it at a different name, which silently changes what this code does instead of fixing it.
- 🚨 `backend.services.get_suppliers` is read at line 20: `backend.services` defines DB_PATH, get_stock_level, get_stock_levels_by_warehouse, low_stock_report, and no `get_suppliers`. This raises on every call that reaches it. Add `get_suppliers` to `backend.services` — do NOT delete the reference or point it at a different name, which silently changes what this code does instead of fixing it.
- 🚨 `backend.services.create_supplier` is read at line 29: `backend.services` defines DB_PATH, get_stock_level, get_stock_levels_by_warehouse, low_stock_report, and no `create_supplier`. This raises on every call that reaches it. Add `create_supplier` to `backend.services` — do NOT delete the reference or point it at a different name, which silently changes what this code does instead of fixing it.
- 🚨 `backend.services.get_supplier` is read at line 34: `backend.services` defines DB_PATH, get_stock_level, get_stock_levels_by_warehouse, low_stock_report, and no `get_supplier`. This raises on every call that reaches it. Add `get_supplier` to `backend.services` — do NOT delete the reference or point it at a different name, which silently changes what this code does instead of fixing it.
- 🚨 `backend.services.update_supplier` is read at line 42: `backend.services` defines DB_PATH, get_stock_level, get_stock_levels_by_warehouse, low_stock_report, and no `update_supplier`. This raises on every call that reaches it. Add `update_supplier` to `backend.services` — do NOT delete the reference or point it at a different name, which silently changes what this code does instead of fixing it.
- 🚨 the project's own test suite does not run: 5 of its tests error before executing
- 🚨 FAILED tests/test_main.py::test_list_suppliers_returns_list - AttributeError:...
- 🚨 FAILED tests/test_main.py::test_create_supplier_returns_created - AttributeEr...
- 🚨 FAILED tests/test_main.py::test_get_supplier_not_found_404 - AttributeError: ...
- 🚨 FAILED tests/test_products.py::test_create_product - AttributeError: module '...
