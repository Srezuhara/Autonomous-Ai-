# Phase 23 A2 — live matrix results

*Run 2026-09-12T14:28:50*

Pass criterion (fixed before any build ran): **>= 3 of 4** reach `done` or `done_with_context` with a downloadable ZIP, and every build that boots reports **0 5xx** from the runtime smoke test.

**Result: 4 of 4 rows meet BOTH halves.** 4 shipped a valid ZIP.

> Both halves are now read from the API. The second one — did the artifact actually run — used to exist only as a line in the server log, so this file reported the first half and told the reader to grep for the rest. A row passes it when every check either verified the artifact or correctly did not apply, and at least one check executed it: four not-applicables are not evidence, and a check that never ran is a hole, not a pass. `generated_tests` is reported but does not decide a row — it asks whether the suite the build *ships* runs, not whether the thing built works, and a build can serve every route it declares while its generated tests do not collect.

| Row | Shape | Status | Verified | Tokens | Duration | Files | ZIP |
|-----|-------|--------|----------|--------|----------|-------|-----|
| 1 | simple FastAPI + SQLite CRUD | `done` | yes | 69,236 | 471s | 20 | yes *(earlier run)* |
| 2 | medium FastAPI + JS frontend | `done` | yes | 93,797 | 762s | 23 | yes *(earlier run)* |
| 3 | complex / multi-entity | `done_with_context` | yes | 128,676 | 965s | 29 | yes *(earlier run)* |
| 4 | non-FastAPI (CLI) | `done` | yes | 114,339 | 836s | 16 | yes |

## Per-row detail

### Row 4 — non-FastAPI (CLI)

- build_id: `e93af820-10f3-4c64-94a8-f86ded9f2fc5`
- status: `done`
- progress: 100.0%
- tokens by model: `{"openai/gpt-oss-20b": 74917, "openai/gpt-oss-120b": 39422}`
- download: HTTP 200, application/zip, 13,894 bytes
- expected to boot: no (smoke test must skip cleanly)
- build shape: cli
- smoke: not applicable — this build is cli, with no web app to probe
- verified: **yes** — verified by cli_smoke; for manual testing: generated_tests

| Check | Status | What it did |
|---|---|---|
| `runtime_smoke` | not_applicable | this build ships no web application to probe |
| `cli_smoke` | verified | ran 2 CLI entry point(s): bulk_file_renamer_e93af820/src/cli.py, bulk_file_renamer_e93af820/src/main.py |
| `web_assets` | not_applicable | this project ships no HTML page |
| `static_smoke` | not_applicable | this project ships no HTML page |
| `package_smoke` | not_applicable | this project is run, not imported; its own verifier covers it |
| `feature_coverage` | verified | 4/4 requested feature(s) have supporting code (0 route(s), 16 function(s) across cli) |
| `schema_attr` | not_applicable | this project declares no pydantic models |
| `module_ref` | verified | 10 module(s) checked name-by-name (1 skipped as open) |
| `sql_schema` | not_applicable | this project creates no tables inline, so there is no schema here to check SQL against |
| `dead_events` | not_applicable | this project builds no FastAPI app with a lifespan, so there is no handler here that a lifespan could disable |
| `route_presence` | not_applicable | this project is not a web API, so it is not expected to declare routes |
| `call_arity` | verified | 2 call(s) checked against their definitions |
| `await_sync` | not_applicable | this project awaits nothing, so there is no coroutine mismatch to find |
| `generated_tests` | failed | pytest exit 1, 2 failed, 10 passed |

- 🚨 the project's own test suite fails: 2 failed, 10 passed
- 🚨 FAILED tests/test_cli.py::test_main_calls_bulk_rename_and_undo_log - TypeErro...
- 🚨 FAILED tests/test_main.py::test_main_success_with_mocks - assert 1 == 0
