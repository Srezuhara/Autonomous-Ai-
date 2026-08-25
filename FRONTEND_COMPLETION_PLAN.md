# Complete, polish, integrate and verify the frontend

> **Approved plan · created 2026-08-25.** Copy of the working plan, committed to
> the repo so a new session can pick it up. The authoring copy lives at
> `C:\Users\KIIT0001\.claude\plans\ok-complete-all-the-harmonic-knuth.md`.
>
> Read alongside `FRONTEND_REDESIGN_HANDOFF.md`, which carries the verified
> commands, the locked design archetypes (§3) and the validated chart palette
> (§4). This file is the *plan*; that file is the *state*.

---

## EXECUTION STATUS — read this first

> **This plan is FULLY EXECUTED as of 2026-08-25.**
> Every phase below (1 through 5) has landed and is verified. Do not re-run it.
>
> The document is kept as the record of *what was decided and why*. For the
> current state of the codebase, start with **`SESSION_PROGRESS.md`**, then
> `FRONTEND_REDESIGN_HANDOFF.md`.

| Phase | State |
|---|---|
| 1 — Finish the remaining surfaces | done |
| 2 — Collapse the surface vocabulary | done |
| 3 — Backend integration (incl. the 4 backend edits) | done |
| 4 — Skill-driven anti-slop polish (all 4 skills) | done |
| 5 — Verification (Vitest, Playwright, axe, contract tests, docs) | done |

Verified at completion: typecheck / lint / build clean, 191 unit tests,
64 E2E tests, 216 backend assertions, 0 npm vulnerabilities, 0 CVEs in any
request-path Python package.

---

## Context

The redesign is about two-thirds done. `Landing`, `NewBuild`, `BuildProgress`,
`ProjectDetail`, `Sidebar`, `FloatingStatus`, `StepTracker` and `StatusBadge`
sit on the new design system (`styles/app-shell.css` + `styles/primitives.css`).

Exploration found the remaining work is substantially bigger than "Dashboard is
left", and — more importantly — found **real integration defects, including
several in screens already shipped as finished**:

**Unfinished surfaces**
- `Dashboard` is entirely untouched (legacy `.card`, own header markup, old
  `.tab-group`, old 400ms `animate-in`).
- `BuildCard` and `RebuildModal` untouched. `RebuildModal` is 437 lines of which
  **~260 are a CSS-in-JS template literal injected via `<style>` on every
  mount** — a parallel stylesheet with `transition: all`, its own chip/tab
  vocabulary, hardcoded rgba, and no focus trap, Escape handler or `role="dialog"`.
- `Statistics` is half-converted: charts are new, but its header, KPI row and
  entire token section are legacy with **19 inline `style={{}}` blocks**.

**Structural debt**
- **Three names for one surface** — `.panel`, `.card`, `.viz-card` — and
  `.viz-card` uses `--radius-xl` where `.panel` uses `--radius-lg`, visible
  whenever a chart sits beside a panel.
- **~750 lines of dead code**: `BuildLogsPanel.tsx` (596, imported nowhere,
  contains a looping animation and 11 hardcoded hexes), `ui/card.tsx`,
  `ui/spotlight.tsx` (both dead and both reference Tailwind tokens/animations
  that are never defined — they would render broken).
- **Tailwind is installed and imported with zero utility classes in any live
  file**; its only consumers are the two dead components.
- **No mobile navigation** — a fixed 240px sidebar leaves ~50–80px of content
  below 600px, silently clipped by `body { overflow-x: hidden }`.
- **No test runner of any kind.** `setup.md` documents `npm run test` and
  `pytest tests/ -v`; neither exists.

**Live bugs (the important part)**
- A **cancelled** build renders "Build complete — your files are ready to
  download" on `BuildProgress`.
- Pipeline **failures never display at all**: the failure event is emitted as
  `step: -1`, and `StepTracker` only renders slots 1–9.
- Steps **5, 8 and 9 collide** (two agents each). The hook dedupes by step
  number, so the wrong agent name shows, and React gets duplicate keys.
- `project.error` is read in three places but **the column does not exist** —
  the "What went wrong" panel is always the fallback string. The real text is in
  `completion_reason`.
- **Prompt limit conflict**: the composer allows 2000 chars, the API rejects
  above 500 with a 422.
- `status: "pending"` has no badge mapping → renders as a raw lowercase chip.
- The outcomes chart **excludes `pending`/`queued` from its total** while its
  header says "N builds total", so every percentage is wrong.
- `StepTracker` renders `step.data.message`, which the backend never emits —
  dead markup.
- The Landing page presents **invented metrics as real** ("150+ Projects built",
  "98% Success rate", "18 Endpoints" — there are 17).
- The REST polling fallback and WS history replay both **drop step `data`**, so
  after a reconnect all elapsed times and error payloads vanish.
- `DELETE /projects/cleanup` is **permanently unreachable**, shadowed by
  `DELETE /projects/{build_id}` because of router include order.

## Decisions taken

| Question | Answer |
|---|---|
| Backend scope | Frontend-first. Additive changes plus **low-risk bug fixes**. **`agents/pipeline.py` is off limits** — step-number collisions get frontend tolerance, not renumbering. |
| Prompt limit | **Widen the backend to 2000** to match the composer. |
| Landing metrics | **Wire to real `/stats`**, with an honest fallback when empty or offline. |
| Testing | Committed suite: **Vitest + Testing Library** (component) and **Playwright + axe** (E2E). |
| Dead code | **Remove all of it**, including the Tailwind pipeline. |
| Mobile | **Responsive sidebar drawer** — focus trap, Escape, route-change close. |

## Constraints that must hold

- Vite on **5173**; the CORS allowlist is not to be rewritten (the dev proxy in
  3.4 makes it irrelevant rather than editing it).
- Archetypes are **locked and not being re-rolled**: Ethereal Glass (`#050507`,
  radial mesh, hairline borders) + Asymmetrical Bento. Geist / Geist Mono /
  Instrument Serif italic accent.
- The **CVD-validated chart palette is not re-derived**. Blue stays out, violet
  is the brand, `cancelled` stays achromatic.
- Motion split by surface: Landing polish-forward; app screens restraint
  (sub-200ms or nothing); **nothing loops** except work genuinely in flight.

---

## Phase 1 — Finish the remaining surfaces

**1.1 `Dashboard`** — rebuild on `.page-head` / `.panel`.
Header → `.page-head` with mono kicker and one `<em>` accent; refresh in
`.page-head__aside`; **drop the "New Build" button** (the sidebar pins that
action now). KPI row → shared `.panel` + `.ulabel` + `.figure`, replacing the
local `MetricCard` and its inline `style={{ color }}`. Filters →
`.chip[aria-pressed]` instead of `.tab-group`/`.tab` (which carries
`transition: all`). `animate-in` → `app-enter`. Add the missing `cancelled` /
`queued` filters. Loading/empty/error states rebuilt on `.panel`. Use the
envelope's `total` rather than `projects.length`.

**1.2 `BuildCard`** — `.card card--interactive` → `.panel panel--interactive`
(that modifier already exists and is currently unused). Replace the ad-hoc
`.score-chip` vocabulary with `.ulabel` + `.figure` (today `.score-chip-value`
uses `--font-display`, so scores jitter between rows). Delete the duplicate
`@keyframes spin`. Lift `parseScorePct()` out of `ProjectDetail.tsx` into
`lib/scores.ts` and reuse it here, instead of `.toFixed()` on one field and
`.split('/')` on two others.

**1.3 `RebuildModal`** — the largest single cleanup. Delete the 260-line
`MODAL_CSS` literal; move to `RebuildModal.css` built from `.panel`, `.chip`,
`.ulabel`, `.btn`. Add `role="dialog"`, `aria-modal`, `aria-labelledby`, focus
trap, Escape-to-close and focus restoration — none of which exist. Mode tabs and
suggestions → `.chip`. Reuse the `NewBuild` composer pattern so both textareas
in the product behave identically, including the same 2000-char contract.
`backdrop-filter` stays here: a fixed overlay is the allowed case.

**1.4 `Statistics`** — finish the half-conversion. Header → `.page-head`; range
tabs → `.chip[aria-pressed]`; KPI row → the same tile as 1.1. **Rewrite the
token section**, where all 19 inline style blocks live: the input/output split
becomes the shared `.meter`. Delete the 7 dead selectors orphaned when charts
moved to `viz-*`. Surface `builds_today` / `builds_this_week` /
`average_review_score`, which the API returns and nothing renders.

**1.5 Responsive sidebar** — below 900px the sidebar becomes an off-canvas
drawer behind a compact top bar carrying the route name. Focus trap, Escape,
close on route change, `aria-expanded`/`aria-controls`, content behind marked
`inert`. Transform-only, ~200ms, honouring `prefers-reduced-motion`. State in
`App.tsx`; `Sidebar.tsx` takes `open`/`onClose`.

**1.6 Deletions** — `BuildLogsPanel.tsx`, `ui/card.tsx`, `ui/spotlight.tsx`,
`lib/utils.ts`, and the two never-imported barrels. Remove `tailwindcss`,
`@tailwindcss/postcss`, `clsx`, `tailwind-merge`, `autoprefixer`,
`postcss.config.js`, `tailwind.config.js`, and the `@import "tailwindcss"` line.
Prune the unused `lib/motion.ts` exports except any the drawer/modal adopt.
**(Partially applied — see EXECUTION STATUS at the top.)**

---

## Phase 2 — Collapse the surface vocabulary

`ChartFrame` renders `.viz-card` → `panel panel--pad`; `.viz-card__title/__hint`
→ the shared label scale; `.viz-stack__bar` → `.meter`; `.viz-empty` → the
shared empty state. This removes the radius mismatch.

Once nothing references `.card`, remove it from `globals.css`. Remove the
remaining dead selectors (`.badge-info`, `.divider`, `.text-gradient`,
`@keyframes fadeInScale`, `.toolbar__spacer`). Tokenise the last hardcoded
colours: the `.btn-primary` gradient, and the `#0B0713` literal duplicated in
`Sidebar.css` and `primitives.css` — which currently **disagree** with
`--text-inverted` (`#050507`).

---

## Phase 3 — Backend integration

### 3.1 Fix the live bugs (frontend side)

| Bug | Fix |
|---|---|
| Cancelled build reads "Build complete" | Add a `cancelled` branch to the title/subtitle logic in `BuildProgress.tsx` |
| Failures never render (`step: -1`) | `StepTracker` renders slots 1..N **plus** any out-of-range event as a terminal failure row; `BuildProgress` shows the failure prominently |
| Steps 5/8/9 collide | Key on `step + step_name`, keep the latest event per slot, and show the true emitted name rather than the fallback map |
| `project.error` never exists | Read `completion_reason`; keep `error` only as an optional extra |
| `pending` has no badge | Add it to `STATUS_MAP` (neutral + Clock), and to `STATUS_ORDER` in the outcomes chart so percentages stop lying |
| `step.data.message` never emitted | Render what the backend actually sends — `elapsed_seconds`, `avg_score`, error text — and drop the dead branch |
| Poll/replay drop `data` | Preserve `data` in the polling merge; don't overwrite a richer WS step with a poorer polled one |
| `done_with_context` as a *step* status | Add it to the step-status union and render it as a warning, not "pending" |

### 3.2 Surface data the API already returns

`/jobs/{id}/status` provides `elapsed_seconds`, `estimated_remaining_seconds`,
`progress.percent`, `remaining_steps`, `total_steps`, `queue_position` — all
discarded today. Widen `useBuildProgress` to return them and render elapsed +
ETA + queue position on `BuildProgress`.

### 3.3 Stop hardcoding what the backend knows

Drive step count from `total_steps` (keep names as a labelled fallback, and fix
the fallback: **step 9 is `documenter`, not "Packager"** — a name that does not
exist in the pipeline). Wire the Landing proof rail to real `/stats`. Derive the
"Groq keys rotate" copy from `llm.provider` rather than asserting Groq. Move the
`$0.59`/`$0.79` pricing constants into one module instead of two drifting copies.

### 3.4 Remove the port/CORS trap

Add `server.proxy` to `vite.config.ts` and make `BASE_URL` relative by default.
Requests become same-origin, so the "wrong port → everything blocked → looks
like a frontend bug" failure documented in the handoff cannot recur, and
`127.0.0.1` vs `localhost` stops mattering. **Frontend-only.**

### 3.5 Backend changes — additive and low-risk only

1. **`models.py`** — `BuildRequest.max_length` 500 → 2000. Widening only.
2. **`main.py` router order** — include `analytics_router` before
   `projects.router` so `DELETE /projects/cleanup` stops being shadowed.
   Verify no other literal path is affected.
3. **`main.py` CORS** — add `http://127.0.0.1:5173` alongside the existing
   origins. Purely additive; the existing entries are untouched.
4. **SPA mount** — a guarded `StaticFiles` mount serving `frontend/dist` only
   if it exists, registered **last** so it cannot shadow an API route, with a
   history fallback for client-side routes. With no `dist/` present the backend
   behaves exactly as it does today. This is the "seamlessly combine" step:
   after it, one command serves the whole product.

**Explicitly not touched:** `agents/`, `tools/`, `prompts/`, `runner.py`,
`database.py` schema.

---

## Phase 4 — Skill-driven anti-slop polish

Runs **after** every surface is on the system, so the skills audit the finished
app rather than a half-converted one.

| Skill | Mode | Scope |
|---|---|---|
| `design-taste-frontend` | audit-first | Whole app — the explicit anti-slop pass |
| `ui-ux-pro-max` | review | Hierarchy, affordance, empty/error states, a11y |
| `design-motion-principles` | **audit** | Every transition, hunting AI-slop motion |
| `high-end-visual-design` | apply | Spacing rhythm, optical alignment, edge quality |

The locked archetypes are the boundary: skills refine execution, they do not
re-roll direction. Where a recommendation conflicts with a locked decision or
the validated palette, **the locked decision wins** and the conflict is recorded
in the handoff.

Targets already known, independent of what the audits surface:
- `index.html` still says `<title>frontend</title>`. Needs a real title, meta
  description, `theme-color`, and `preconnect` for `fonts.gstatic.com` (the font
  `@import` is currently render-blocking behind the CSS parse).
- Focus-visible is inconsistent — only `.panel--interactive` and `.chip` have
  deliberate states.
- Empty and error states are the least-designed surfaces in the app.
- Route-level `React.lazy` on `Statistics` to move Recharts out of the initial
  chunk (820 kB / 250 kB gzip, unaddressed since the redesign began).

---

## Phase 5 — Verification

**5.1 Static** — `tsc -b` and `npm run lint` clean; add the missing `typecheck`
script. Report (not silently change) that `tsconfig.app.json` has **`strict`
absent**, so `strictNullChecks`/`noImplicitAny` are off.

**5.2 Component tests** — Vitest + Testing Library + jsdom, `npm run test`.
Behaviour, not snapshots: every backend status string maps to a real badge
(including `pending`); `StepTracker` renders each state and the `step: -1`
failure; `NewBuild`'s submit guard, readout state machine and Ctrl+Enter;
`RebuildModal` focus trap / Escape / focus restoration / both submit payloads;
`Dashboard` and `ProjectDetail` loading/empty/error/populated;
`useBuildProgress` WS merge, the `'undefined'` guard, step collisions, and
polling promotion to terminal.

**5.3 E2E** — Playwright, `npm run test:e2e`, against live servers:
zero console errors and no failed requests per route; **no horizontal overflow**
at 1440/1024/820/640/420, measuring `scrollWidth` vs `clientWidth` **and**
scanning element rects (because `overflow-x: hidden` masks the first check);
`prefers-reduced-motion` → zero elements declaring motion; **zero infinite
animations** except the active-step spinner; drawer opens/traps/Escapes/closes
on nav; keyboard-only traversal reaches every control with a visible focus ring;
and the full journey — dashboard → new build → submit → WS progress → detail →
rebuild.

**5.4 Accessibility** — `@axe-core/playwright`, zero serious/critical per route.
There is no a11y tooling today.

**5.5 Integration** — a contract test asserting every path in `api/client.ts`
exists on the running backend; a 2000-char prompt now succeeds end-to-end;
`DELETE /projects/cleanup` is reachable; deep links like `/projects/{id}` resolve
from the SPA mount with only the backend running. Re-run `test_phase17.py`,
`test_phase21.py`, `test_phase22.py` and `test_groq_rate_limit_handling.py` to
prove the backend edits broke nothing. `git status` reviewed deliberately.

**5.6 Docs** — update `FRONTEND_REDESIGN_HANDOFF.md` (status, new traps,
measured results) and `setup.md`, whose documented `npm run test` finally becomes
true.

---

## Sequencing

Phases 1 → 2 → 3 land before 4, so the skills audit a finished app. Typecheck
and build run after **every** phase, not saved for the end. 5.1/5.2 grow
alongside 1–3; 5.3–5.5 run once at the end.

**Risk note:** the only changes that can break the working pipeline are the four
in 3.5. Each is independently revertible, and the Python test scripts run
immediately after them rather than at the end of the whole plan.

---

## Reference — verified commands

```bash
# Frontend dev server — the port is NOT optional (backend CORS allowlist)
cd frontend && npm run dev -- --port 5173 --strictPort

# Backend. Needs the venv — system Python lacks `rich` and dies on import.
venv/Scripts/python.exe start_server.py       # serves :8000

# Typecheck / production build
cd frontend && npx tsc -b && npm run build
```

Live data currently in the DB, useful for exercising states:

| build_id | status | exercises |
|---|---|---|
| `fb3e4b24-5491-4925-bdb2-4a096df4735f` | `done_with_context` | handoff banner, scores, tokens |
| `fa7533e1-26bc-4ce6-9f0f-502d823e6632` | `failed` | failure path |
| `941887e1-6602-4c1d-9a89-5bc938b279c7` | `running` | live WS spine |
| `d715e3f9-ac30-4d62-947c-97976c75d87e` | `cancelled` | the "Build complete" bug in 3.1 |
