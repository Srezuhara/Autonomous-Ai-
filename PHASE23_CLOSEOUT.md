# Phase 23 — closeout

*Written 2026-09-12, the seventeenth session. This file closes Phase 23. It
records what the four matrix rows actually produce, measured by hand against the
running artifacts, and what a person who downloads one has to do next.*

Read `PHASE23_MATRIX_RESULTS.md` for the machine-written record of the last run
of each row. This file is the judgement on top of it.

---

## 0. The decision that closes the phase

The pass criterion fixed before any build ran was:

> **>= 3 of 4** reach `done` or `done_with_context` with a downloadable ZIP, and
> every build that boots reports **0 5xx** from the runtime smoke test.

On 2026-09-12 the user set the bar the phase should actually close on:

> the app doesnt need to be working perfectly just the basic structure should be
> there so that people can work upon it and if the app is not completely working
> then proper context should be given what the user needs to do and what can he
> check manually

**All four rows meet that bar, and the phase is closed on it.** The stricter
numbers are kept below rather than discarded, because they are the honest
measurement and a later session should not have to re-derive them.

### Three readings of the matrix, all true

| Reading | Result |
|---|---|
| **The user's closing bar** — structure present, honest context shipped | **4 of 4** |
| **The written criterion, read literally** — >= 3 of 4 `done`/`done_with_context` + ZIP, and 0 5xx from the runtime smoke on builds that boot | **4 of 4** |
| **The driver's criterion** — every check `verified` or correctly `not_applicable`, and at least one check executed the artifact | **2 of 4** (rows 1, 3) |

The three disagree for one reason and it is worth stating plainly. The driver is
stricter than the sentence it claims to implement: the written criterion talks
about 5xx from the *runtime smoke test*, while the driver fails a row when *any*
check fails, including `cli_smoke` and `sql_schema`. That strictness was adopted
deliberately (see the blockquote in `PHASE23_MATRIX_RESULTS.md`) and is not a
bug — but it means "2 of 4" is not the same claim as "two rows do not work".
**Rows 2 and 4 both run.** What they are missing is narrower than their status
suggests, and section 2 says exactly what.

---

## 1. What this session changed

`test_phase23.py`: **1122/1122** (was 1112). Corpus: no regressions — 43 "new
check" entries, the documented never-baselined noise, and one real diff
(`inventory_system_e6a1da32/feature_coverage: verified -> not_run`), which is the
known pair already recorded.

Two defects in the handoff document, both found by reading what a real build
shipped rather than by reasoning about the code:

1. **The handoff claimed a verification that never happened.** The
   "Worth Checking By Hand" preamble asserted *"The application itself was
   executed and verified"* for every build with any manual-check item. Row 2's
   `01cde425` shipped that sentence two inches below a Remaining Work list saying
   6 of 6 endpoints return 500. It is now conditional on the pipeline's own
   `unresolved` signal. Missing tests deliberately do **not** trip it: a verified
   build can legitimately ship no suite, and calling that "broken" would repeat
   the error in the other direction. **Confirmed live** on row 2's new build,
   which now opens that section with *"The application has unresolved issues —
   see Remaining Work above, and start there."*
2. **The handoff listed only defects, so a working app read as broken.** Row 2
   serves all five CRUD endpoints and its document mentioned none of it. A
   **What Already Works** section is now built from
   `result.verification_outcomes`, using only checks that **executed the artifact
   and passed**. `not_applicable`, `not_run` and `failed` are all excluded — a
   check that did not look at something is not evidence that the something
   works — and when nothing qualifies the section is omitted rather than left
   empty. Unit-tested against row 2's real recorded outcomes.

> **The second change takes effect on the NEXT build.** The two builds below were
> generated before it was wired in, so their shipped `SESSION_CONTEXT.md` has the
> corrected preamble but not the "What Already Works" section. Their docs were
> not rewritten by hand — a handoff is a record of what the pipeline observed,
> and editing one after the fact would make it evidence of nothing.

---

## 2. The four rows, and what a person downloading one must do

### Row 1 — simple FastAPI + SQLite CRUD · `156f73a3` · `done` · verified

Works. 5/5 routes. Nothing to do by hand.

### Row 3 — complex / multi-entity · `1134f369` · `done_with_context` · verified

Works. 21/21 routes across four entities. Nothing to do by hand.

### Row 4 — CLI bulk file renamer · `bc9d1317` · `done_with_context` · 80,093 tokens

**This is the first row-4 build in the project's history to satisfy the whole
prompt.** The previous eight did not; the record said "0 of 8". Hand-run against
a scratch directory:

| Prompt requirement | Result |
|---|---|
| rename files in bulk | works |
| takes directory, match pattern, replacement | works |
| `--dry-run` flag | works — lists the renames, changes nothing |
| undo log so a rename can be reversed | works — reverted both files |

```bash
python bulk_file_renamer/cli.py <dir> -p "report=>summary" --dry-run
python bulk_file_renamer/cli.py <dir> -p "report=>summary"
python bulk_file_renamer/cli.py <dir> -p "x=>y" --undo
```

**What is wrong, and it is real.** The build ships a *second*, redundant entry
point, `bulk_file_renamer/main.py`, with a different flag interface (positional
`[pattern] [replacement]`, `-d`, `-u`). It crashes on the rename path:

```
AttributeError: 'str' object has no attribute 'rglob'
  renamer.py:17 in _iter_files  <-  main.py:50 in bulk_rename
```

`_iter_files(pattern)` is handed a `str` where a `Path` is expected.
`cli_smoke` correctly failed the build for it. `call_arity` passed it, because
the argument **count** is right and only the **type** is wrong — the
"count right, meaning wrong" class already recorded in the notes, and the
standing argument for the annotated-type comparison that is still unbuilt.

**To do by hand:** use `cli.py`. Either delete `main.py` or fix the one call
(pass `Path(...)`, and reconcile its flags with `cli.py`'s). The shipped test
suite fails 3 of 12, mostly against `main.py`.

### Row 2 — bookmark manager, FastAPI + JS frontend · `464da0fb` · `done_with_context` · 90,937 tokens

**Went from `unusable` (0/6 routes) to 6/6 routes responding.** Two fixes from
the previous session both landed and are now proven live: the `backend_developer`
prompt's thread rule (`check_same_thread=False`) and `Debugger._repair_db_paths`,
which resolved the two-database defect that had recurred across four builds.

Probed by hand over HTTP against a clone:

| Endpoint | Result |
|---|---|
| `POST /bookmarks` | 201 |
| `GET /bookmarks` | 200 |
| `GET /bookmarks/{id}` | 200 |
| `PUT /bookmarks/{id}` | 200 |
| `DELETE /bookmarks/{id}` | 204 |
| `GET /tags` | 200 (`[]`) |

**What is missing.** Three things, none of which is a crash:

1. **Tag filtering was never wired.** `list_bookmarks_by_tag` is defined in
   `backend/routes.py` but no route reaches it, so the prompt's "filters by tag"
   is absent. **This also explains the one open `sql_schema` finding**: that
   function joins `bookmarks_tags`, a table the project never creates (it
   creates `bookmark_tags`). The finding is correct that the table is missing
   and correct that any call would raise — but **nothing calls it**, so it is
   latent dead code, not a live 500. The handoff says "Every call that reaches
   this query raises `no such table`" without saying nothing reaches it.
2. **`tags` is accepted and silently dropped.** `BookmarkCreate` declares
   `tags: Optional[List[str]]` and `BookmarkRead` declares
   `tags: List[TagRead]`, but the responses carry only `url`, `title`,
   `description` — no `id`, no `tags`.
3. **The frontend is not served by the backend.** `frontend/index.html`,
   `main.js` and `style.css` exist and all four of the page's `fetch` calls
   target endpoints that work, but there is no `StaticFiles` mount, so `/` is
   404. Open the file directly or serve `frontend/` separately.

**To do by hand:** add the `bookmarks_tags` CREATE TABLE (or point the query at
the `bookmark_tags` that exists — but decide which schema you want first), wire a
`GET /tags/{tag}/bookmarks` route to `list_bookmarks_by_tag`, thread `tags`
through the response models, and mount the frontend. The shipped test suite
fails 14 of 17 and is not a reliable guide here.

---

## 3. What is still open

* **The first-order defect is unchanged: generation quality, not verification.**
  Every check that fired this session was correct, and none fired on working
  code. Both remaining failures are things the generator produced (a redundant
  broken entry point; an unwired feature), not things the checks got wrong.
* **`call_arity` compares counts, not types.** Row 4's `main.py` is the clearest
  case yet for the annotated-type comparison that has been an idea for three
  sessions. Falsify it on the corpus before trusting it — 4 of 6 new verifiers
  have reported defects that did not exist.
* **A finding can be latent.** Row 2's `sql_schema` hit is real and unreachable
  at once. Nothing currently distinguishes "this query is broken" from "this
  query is broken and no route reaches it", and the difference decides whether a
  user should care.
* **`generated_tests` still fails on essentially every build** and still has no
  repair channel. It does not decide a row.
* Everything carried in `pipeline-open-defects` that this session did not touch.

---

## 4. Operational

Both rows this session ran with the server restarted first and confirmed newer
than every source file. Quota was full at the start (no spend in the window) and
both rows ran without hitting a floor; the run was throttled by Groq's
per-minute budget, not the daily one, which is why row 2 took 649s.

`--rows 4` and `--rows 2` were run as **separate** invocations. `--rows 4,2` runs
in matrix order, and row 2's fast-model spend has previously pushed row 4 under
its start floor.

---

## 5. Addendum, 2026-09-12 — the matrix reached 3 of 4

The phase closed above on the user's bar. Later the same day the question "can a
stronger Groq model make verifiable builds?" was investigated, and the answer
turned out to be **no, because the blocker was not a model**.

Two things were established before changing anything:

* `gpt-oss-120b` is already the largest general model Groq serves these keys.
  There is no bigger option. (`qwen/qwen3.8-27b` is the only untested candidate;
  deferred.)
* **The `debugger` agent made ONE LLM call in row 2's entire build and zero
  during either remediation pass.** Moving it to a stronger model would have
  relocated one call. The claim that "repairs run on the weakest model" was
  wrong, and checking call volume rather than the routing table disproved it.

### The actual defect: a checker counted test fixtures as application schema

`check_project_sql` scanned every `.py` file for `CREATE TABLE`, tests included.
A table created only in a generated fixture therefore counted as one the project
creates, masking a table the **application** never creates. Because the Tester
rewrites those fixtures on every remediation pass, the mask lifted and fell
between passes:

```
12:29:48  ✅ Every table the code queries now exists    ← gate
12:29:48  🔁 Remediation pass 2/2                       ← routes.py never modified
12:31:01  🚨 routes.py queries `bookmarks_tags`, never created
```

By the time the defect was visible, both repair passes were spent. The
`_is_test_file` helper already existed and was already applied to the sibling
db-path scan — with a docstring saying exactly why — but not to this one.

Three changes: exclude tests from the schema scan; never target a repair at a
test file; and make the between-pass gate follow the check's own verdict instead
of the emptiness of its repair-target list (a `FAILED` check that published no
target printed as a pass — `silence-is-not-a-pass`).

**Falsified**: with `_is_test_file` stubbed to `False`, the mask returns and the
checker reports nothing missing. **Corpus: zero `sql_schema` diffs** across the
whole corpus; rows 1 and 3 hand-checked, `not_applicable` before and after.
`test_phase23.py` 1122 → **1131**.

### Row 2 `3aea19e3` — `done`, and the first 3-of-4 matrix

**0/11 routes → 11/11 after a single remediation pass.** Status `done` (not
`done_with_context`), 93,797 tokens, 762s. Every channel fired: runtime repair,
database-path repair, field repair, and the table repair that the masked check
had prevented. This build also declares the `by_tag` filter route the previous
build omitted entirely, and returns `id` and `tags`, which it dropped.

**The matrix now meets its ORIGINAL fixed criterion: 3 of 4.**

### What `done` still overstates, and why

Hand-run against a clone, `POST /bookmarks/` with the optional `tags` field
returns **500**. Two causes, both open:

1. **The repair satisfied the checker, not the defect.** `schema_attr` reported
   `payload.tags` read but undeclared; the repair declared
   `tags: List[TagRead]` on `BookmarkCreate`, while the handler iterates those
   entries as tag *names* (`SELECT id FROM tags WHERE name = ?`). Every shape a
   caller can send is now rejected (422) or 500s. This is the standing
   first-order defect in its clearest form yet.
2. **`runtime_smoke` sends required fields only** — `_example_model` is
   documented as "the smallest body the model will accept". A defect reachable
   only through an *optional* field cannot be seen by it. That is a structural
   hole, and it is how an 11/11 build ships a 500.

Also unchanged: `description` is accepted and silently dropped —
`INSERT INTO bookmarks (url, title)` never stores it.

**Next task, ahead of the `call_arity` type work:** decide whether
`runtime_smoke` should probe optional fields too. Do not just switch it on —
sending every optional field would change the verdict on every build in the
corpus. Measure first.

---

## 6. Clean builds now ship a handoff document too

The honesty machinery was inverted. `SESSION_CONTEXT.md` is written only for
`done_with_context` and `unusable` builds, so the builds that **failed**
explained themselves in detail, and a build that passed every check shipped
`README.md` and `SETUP.md` and nothing else.

`3aea19e3` is why that matters. Status `done`, 11/11 routes, every check
verified — and by hand: `POST /bookmarks/` returns **500** whenever the optional
`tags` field is supplied, the frontend is **not served** (no `StaticFiles`
mount, so `/` is 404), `description` is accepted and silently dropped, and 4 of
its 9 shipped tests fail. A user received none of that.

**`BUILD_REPORT.md`** is now written on the clean-success path
(`Pipeline.run`'s final `else`) and picked up by the ZIP automatically —
`downloads.py` rglobs the project and `.md` is not in `FORBIDDEN_FILES`.

It is deliberately **not** `SESSION_CONTEXT.md`. That document's every line is
framed as "this build did not finish cleanly"; telling someone their working
build failed would be the same defect mirrored. `BUILD_REPORT.md` answers a
different question, in four sections:

1. **What was verified** — only checks that executed the artifact and passed.
2. **What was NOT checked** — `not_applicable` *and* `not_run`, kept separate
   from each other and from a pass, because a check that did not look is not
   evidence that the thing works.
3. **Worth checking by hand** — whatever was routed to manual, which is how the
   4-of-9 failing suite finally reaches the reader.
4. **Known limits of these checks** — the structural holes, stated in the
   artifact the user receives rather than only in this repo's notes: endpoints
   are probed with **required fields only**, frontend JavaScript is **never
   executed**, a passing check means "it did not error" and not "it did what you
   asked", and the generated suite is not a reliable signal.

Section 4 is the one that would have saved this user: it points straight at the
optional-field blind spot that hid the `tags` 500.

Verified: `test_phase23.py` **1143/1143** (+12), including that a clean build is
never told it failed, that `not_run` is never rendered as verified, and that the
pipeline calls the generator on the clean path. The generator was also run
against the real `3aea19e3` tree on a clone — it extracted all 11 endpoints and
the real file tree.

**Not yet exercised by a live build.** The next `done` build will be the first
to write one for real.

---

## 7. The confirmation run — `BUILD_REPORT.md` works, and row 4 proves why it was needed

Row 4 re-ran as `e93af820`: **`done`**, 836s, 114,339 tokens, and it wrote the
first real `BUILD_REPORT.md` (4,331 chars). The matrix file now reads **4 of 4**.

The run crossed the fast floor deliberately (80,219 left against a 90,000 floor)
under the runbook's documented condition — heavy held 89,223, more than row 4's
full previous cost of 80,093. **The fallback then fired for real** at 14:28:11,
moving the Tester to the heavy model when the fast model hit its daily quota.
The override criterion and its safety net both behaved exactly as documented.

`cli_smoke` failed the build at first verification with two real defects, and
remediation repaired both — the first time row 4's recurring two-entry-point
breakage has been fixed by the pipeline rather than carried:

```
cli.py:57   TypeError: bulk_rename() got an unexpected keyword argument 'directory'
main.py:25  AttributeError: 'Namespace' object has no attribute 'path'
→ Runtime repair applied (both), Call repair applied 1/1 → cli_smoke: verified
```

### The document did its job

`BUILD_REPORT.md` listed 4 checks as verified, **9 as not checked** (each with
the reason it did not apply), and carried the failing suite — *"the project's own
test suite fails: 2 failed, 10 passed"* — to the reader. On the old code this
build would have shipped `README.md` and `SETUP.md` and said none of it.

### And the artifact is still broken, which is the point

Hand-run, `pattern` serves double duty: `cli.py:57` uses it as a **glob**
(`directory.glob(pattern)`) while `renamer.py:17` uses the same string as a
**regex** (`re.sub(pattern, replacement, name)`).

* `-p "*.txt"` — the example in the tool's **own `--help`** — glob matches, regex
  raises `re.error: nothing to repeat`, exit 1.
* `-p "report_*.txt"` — valid regex, matches nothing, **exit 0, renames nothing,
  prints nothing**.

`cli_smoke` said `verified` because its probe pattern is valid as both and exits
0. This is the documented "a forward run that exits 0 doing nothing is still
unseeable" hole, and it is the same root defect row 4 has carried for nine
builds — previously through `str.replace`, now through `re.sub`.

**A first false-negative check of the session, and a caution against the
matrix:** 4 of 4 is what the record says; row 4's CLI still dies on its own
documented example. `BUILD_REPORT.md` now carries a CLI-shaped warning for
exactly this — *"a command-line tool that exits 0 is assumed to have worked"* —
because the limits section was otherwise web-only and would not have helped this
user at all.

Also worth keeping: hand-running the CLI through a cp1252 shell reproduced the
old `UnicodeEncodeError` on `\u2011` and looked like a crash in the artifact.
It is not — `cli_smoke` forces UTF-8 on both sides. **A harness can fail working
code with its own console; that has now happened three times.** Export
`PYTHONIOENCODING=utf-8` before hand-running any generated CLI.

`test_phase23.py`: **1144/1144**.
