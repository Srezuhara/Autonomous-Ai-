# Phase 23 A2 — live matrix results

*Run 2026-09-03T03:01:18*

Pass criterion (fixed before any build ran): **>= 3 of 4** reach `done` or `done_with_context` with a downloadable ZIP, and every build that boots reports **0 5xx** from the runtime smoke test.

**Result: 0 of 1 rows meet BOTH halves (matrix incomplete).** 1 shipped a valid ZIP.

> Both halves are now read from the API. The second one — did the artifact actually run — used to exist only as a line in the server log, so this file reported the first half and told the reader to grep for the rest. A row passes it when every check either verified the artifact or correctly did not apply, and at least one check executed it: four not-applicables are not evidence, and a check that never ran is a hole, not a pass. `generated_tests` is reported but does not decide a row — it asks whether the suite the build *ships* runs, not whether the thing built works, and a build can serve every route it declares while its generated tests do not collect.

| Row | Shape | Status | Verified | Tokens | Duration | Files | ZIP |
|-----|-------|--------|----------|--------|----------|-------|-----|
| 3 | complex / multi-entity | `done_with_context` | NO | 114,240 | 873s | 20 | yes |

## Per-row detail

### Row 3 — complex / multi-entity

- build_id: `c2d4a4d4-0871-4e3b-8800-52cb6a6690b2`
- status: `done_with_context` — Build completed with 10 unresolved verification issue(s) after automatic repair. See SESSION_CONTEXT.md.
- progress: 100.0%
- tokens by model: `{"openai/gpt-oss-20b": 58906, "openai/gpt-oss-120b": 55334}`
- download: HTTP 200, application/zip, 21,344 bytes
- expected to boot: yes
- build shape: web_api
- smoke: 13/22 routes responded without a server error
- verified: **NO** — failed: runtime_smoke, schema_attr; for manual testing: generated_tests

| Check | Status | What it did |
|---|---|---|
| `runtime_smoke` | failed | 13/22 routes responded without a server error |
| `cli_smoke` | not_applicable | this project declares no command-line entry point |
| `web_assets` | not_applicable | this project ships no HTML page |
| `static_smoke` | not_applicable | this project ships no HTML page |
| `package_smoke` | not_applicable | this project is run, not imported; its own verifier covers it |
| `feature_coverage` | verified | 6/6 requested feature(s) have supporting code (22 route(s), 48 function(s) across web_api) |
| `schema_attr` | failed | 15 model(s) checked field-by-field (0 skipped as open) |
| `module_ref` | verified | 12 module(s) checked name-by-name (0 skipped as open) |
| `generated_tests` | failed | pytest exit 1, 7 failed, 12 passed |

- 🚨 9 of 22 endpoint(s) return a server error when called: POST /suppliers/ → 500, GET /products/{product_id} → 500, GET /products/ → 500, DELETE /products/{product_id} → 500, GET /stock_movements/{movement_id} → 500. These fail at request time, which the import check cannot see.
- 🚨 `product.price` is read at line 84, but `product` is a `ProductCreate`, which declares description, name, sku, supplier_id. This raises AttributeError on every call that reaches it. Either use the field that exists, or add `price` to ProductCreate where it is defined — do NOT replace the read with a .get() or a default, which writes an empty value into the database instead.
- 🚨 the project's own test suite fails: 7 failed, 12 passed
- 🚨 FAILED tests/test_endpoints.py::test_create_supplier - sqlite3.OperationalErr...
- 🚨 FAILED tests/test_endpoints.py::test_get_supplier - sqlite3.OperationalError:...
- 🚨 FAILED tests/test_endpoints.py::test_update_supplier - sqlite3.OperationalErr...
- 🚨 FAILED tests/test_endpoints.py::test_delete_supplier - sqlite3.OperationalErr...
