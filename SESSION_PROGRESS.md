# Session Progress — start here

**Last session: 2026-08-25 (landing restructure).** `FRONTEND_LANDING_PLAN.md` is
now **fully executed** — all three phases. See §2.7 below for what shipped.
The change is in the working tree and **not yet committed**; the commit before it
is `48d3ae7` "Restructured frontend".

> The motion pass and everything in `FRONTEND_COMPLETION_PLAN.md` (phases 1-5)
> remains executed, verified, committed and pushed as `48d3ae7`.

> **The `.gitignore` blocker described in the old §3.0 is FIXED.** The unanchored
> `lib/` rule was anchored to `/lib/`, the UTF-16 corruption on the last line was
> repaired, and `frontend/src/lib/` is now tracked and on the remote. Nothing to do.

Read this file first. Then:

| File | Role |
|---|---|
| `SESSION_PROGRESS.md` (this) | Current state, what to do next, how to verify |
| `FRONTEND_REDESIGN_HANDOFF.md` | The **state** doc: locked design decisions (§3), chart palette (§4), measured results (§8), gaps (§9), skill conflicts (§10), traps (§11) |
| `FRONTEND_COMPLETION_PLAN.md` | The **plan**, fully executed. Kept as the record of what was decided and why. Do not re-run it. |
| `setup.md` | Setup and commands, rewritten and verified command-by-command |
| `frontend/src/lib/motion.ts` | The motion vocabulary. Every animation in the app imports from here — read it before adding one |
| `motion-audits/aiautonomous-2026-08-25.html` | Motion audit report, all 7 findings applied |

---

## 1. First commands in a new session

```bash
# Backend. MUST be the venv interpreter: system Python lacks `rich` and dies
# on import before the server starts.
venv/Scripts/python.exe start_server.py            # serves :8000

# Frontend dev server (separate terminal)
cd frontend && npm run dev -- --port 5173 --strictPort
```

Then open **http://localhost:5173**.

> **Use `localhost`, never `127.0.0.1`.** Vite binds to whatever `localhost`
> resolves to, which on this machine is IPv6 `::1` **only**. `127.0.0.1:5173`
> is refused at the socket, before CORS or any app code. `npm run dev -- --host`
> binds both if you need the literal IPv4 address.

### Verify nothing has rotted

```bash
cd frontend
npm run typecheck      # tsc -b across app / node / test projects
npm run lint           # eslint
npm run build          # vite build
npm run test           # 191 Vitest, ~15s
npm run test:e2e       # 80 Playwright + axe — needs BOTH servers up
                       # 79 pass, 1 skips, 0 fail (stable over 3 runs).
                       # 5 new: the dashboard status-filter guard, §2.8.

# Backend (test_phase17 needs the server running)
venv/Scripts/python.exe test_phase17.py                  # 54/54
venv/Scripts/python.exe test_phase21.py                  # 77/77
venv/Scripts/python.exe test_phase22.py                  # 85/85
venv/Scripts/python.exe test_groq_rate_limit_handling.py # OK
```

**Known-good baseline:** all clean, 191 unit + 74 E2E (1 skipped) + 216 backend
assertions, 0 npm vulnerabilities, 0 CVEs in any request-path Python package.

The E2E count went 64 → 74 in the motion pass: `e2e/motion.spec.ts` is new. The
one skip is conditional and correct — the step-log accordion test skips when the
fixture build recorded no step logs.

---

## 2. What changed, in one pass

### Frontend surfaces
Every screen is on the design system (`styles/app-shell.css` + `primitives.css`).
Dashboard, BuildCard, RebuildModal and Statistics were the ones finished this
session. `RebuildModal` lost a 260-line CSS-in-JS literal that was injected via
`<style>` on every mount, and gained `role="dialog"`, a focus trap, Escape and
focus restoration — none of which existed.

### One surface vocabulary
`.card` and `.viz-card` collapsed into `.panel`. That fixed a radius mismatch
(`--radius-xl` vs `--radius-lg`) visible wherever a chart sat beside a panel.
Ten dead selector groups pruned; last hardcoded colours tokenised into
`--gradient-accent` and `--text-on-accent`.

### Eight live bugs fixed
- Cancelled builds no longer claim "Build complete — your files are ready".
- Pipeline failures now render at all. The runner emits them on `step: -1`,
  outside the 1..9 range `StepTracker` drew, so a crashed pipeline previously
  showed nine pending rows and no explanation anywhere.
- Steps 5/8/9 no longer collide (each slot runs two agents).
- `completion_reason` replaces `project.error`, a column that does not exist.
- `pending` has a badge; the outcomes chart counts `queued`/`pending` so its
  percentages stop lying.
- Polling no longer drops step `data` — REST returns it as a JSON **string**
  while the socket sends an object; both were discarded.
- `done_with_context` renders as a warning, not "pending".
- Elapsed / ETA / queue position are surfaced (the API always returned them).

### Backend — 4 additive changes only
`agents/`, `tools/`, `prompts/`, `runner.py` and the DB schema are untouched.
1. `models.py` — prompt `max_length` 500 → 2000 (matches the composer).
2. `main.py` — `analytics_router` registered before `projects.router`, so
   `DELETE /projects/cleanup` stops being shadowed by `DELETE /projects/{id}`.
3. `main.py` — CORS gained `http://127.0.0.1:5173` (additive).
4. `main.py` — guarded SPA mount serving `frontend/dist` if present, last, with
   an Accept-header split so `/projects/{id}` returns the SPA to a browser and
   JSON to `fetch`.

### Tests, where there were none
- **Vitest + Testing Library**: 191 tests, 11 files. Behaviour, not snapshots.
- **Playwright + axe**: 64 tests. Overflow at 5 widths, reduced motion, loop
  count, drawer focus trap, keyboard traversal, contract tests, deep links.
- Guards were checked to actually **fail** when their bug is reintroduced.

### Security
npm 7 high → **0**. Python: every request-path package clean.

---

## 2.6 The motion pass

Motion.dev / `framer-motion@12` was already a dependency, and `lib/motion.ts`
already held a motion vocabulary — but it was wired into **only** Landing,
`primitives.tsx` and `RebuildModal`. Every app screen had nothing but a 150ms
CSS fade. This pass extended that existing vocabulary to the whole app rather
than inventing a second one.

### The rule that shapes all of it

`lib/motion.ts` is split into two halves, and the split is the design:

| Half | Surfaces | Budget |
|---|---|---|
| Marketing (pre-existing) | Landing | 300–600ms, blur reveals, heavy glide easing |
| **App (new, below the divider)** | Dashboard, BuildProgress, ProjectDetail, NewBuild, Statistics | enters ≤180ms, exits ≤120ms, throw ≤8px, **no blur**, stagger 0.03 |

No blur on app surfaces is deliberate: the defocus that sells a hero reveal is
paid on every repaint, and on a 50-row build list it is visible jank.

### New exports in `lib/motion.ts`

`appItem`, `appStagger()`, `popIn`, `disclose`, `routeTransition`, `liftable`,
`layoutSpring`, `NAV_RAIL_ID`, `CHIP_ID` — plus **`appListExit`**, added later by
§2.8. Read that entry before giving any AnimatePresence child `exit="exit"`.

### Where motion now lives

| Surface | What moves | Why it earns its place |
|---|---|---|
| `App.tsx` | Route transitions, `AnimatePresence mode="wait"` | Sequential, not cross-fade: pages are normal-flow documents of unknown height, and stacking them absolutely collapses the scroll container mid-navigation |
| `Sidebar.tsx` | Active rail as a single `layoutId` node | One element travels; it is no longer a `::before` (a pseudo-element has no node for Framer to hold) |
| `Dashboard.tsx` / `Statistics.tsx` | Filter + range chip tint, shared `layoutId` | The eye follows the selection instead of re-finding it |
| `BuildCard.tsx` | `layout="position"` + 2px hover lift | Rows surviving a filter change slide rather than teleport. Lift, never scale — scale resamples 11px mono figures and they blur mid-transition |
| `StepTracker.tsx` | Marker spring on status change; meter `scaleX` from zero | A step turning green is the only event on a screen watched for minutes |
| `BuildProgress.tsx` | WS pill, verdict, step count, outcome notes | All keyed to real state changes, not to the dozens of re-renders per build |
| `ProjectDetail.tsx` | Two height-to-auto accordions, rotating chevrons | 9 step logs is several hundred px of movement to absorb |
| `FloatingStatus.tsx` | Pill entry, dot pop keyed on `tone` | Keyed on tone so the 5s poll does not retrigger it |
| `MobileBar.tsx` | Menu ↔ X, quarter-turn crossfade | One control changing meaning, not two trading places |

### Reduced motion

`<MotionConfig reducedMotion="user">` in `main.tsx` is the single switch, so a
new animation cannot forget to opt in. **Verified by measurement that it covers
`layout` / `layoutId` projection too**, not only the animate props — see the
note at the foot of `lib/motion.ts`. Do not add per-component opt-outs; a
`useLayoutTransition` hook was written for this during the pass and then removed
as redundant once measured.

### Three real bugs the verification caught

These were fixed, not tested around:

1. `.chip__active` at `inset: 0` resolved against the **padding** box, so the
   travelling tint stopped short of the chip's 1px border and the pressed chip
   read a shade light around its edge. Now `inset: -1px`.
2. Wrapping the charts for staggering broke `viz-frame--wide`'s full-bleed
   span — the wrapper became the grid item, so the span had to move onto it.
3. The first reduced-motion test used a `test.use({ reducedMotion })` fixture
   that **never reached the page** (`matchMedia` reported `false`). It was a
   test that could not fail, guarding the accessibility behaviour it was named
   after. It now asserts the emulation is live before testing anything.

### `e2e/motion.spec.ts` — what it actually guards

10 tests asserting measured boxes and computed transforms, never "the component
rendered". Route wrapper settles opaque and untransformed; exactly one route
wrapper survives a navigation; one chip tint exists and lands on the pressed
chip; one nav rail lands inside the active link; the meter is `scaleX` (not
width) and agrees with `aria-valuenow`; the accordion opens to exact content
height and closes to zero; and a full walk of every animated surface produces
no console errors.

This is complementary to `layout.spec.ts`, which guards the two motion *rules*
(nothing loops; reduced motion is honoured) by scanning computed CSS. That scan
cannot see Framer at all — Framer writes inline style per frame from JS — so
without `motion.spec.ts` every animation could be broken with both files green.

---

## 2.7 The landing restructure

`FRONTEND_LANDING_PLAN.md`, all three phases. Frontend only; no backend change.
The plan's locked decision — **real data everywhere, nothing fabricated** — held
throughout, and it is what most of the work consists of.

### The bug the plan was right about
`PIPELINE_AGENTS` carried **eight** entries (Architect was missing) while the page
claimed a "9-agent pipeline" in four places. The list is now nine, named exactly as
`STEP_NAMES_FALLBACK` in `StepTracker.tsx` names them.

### A second contradiction, surfaced by the live data
The hero asserted `<8min` average build and the lede said "in under eight minutes"
— while the proof rail three screens down now reads **11.6m** off this instance.
The static claim is gone: the hero's fourth stat is `formatBuildTime(stats)` with
the label "Avg build here", the lede no longer quotes a duration, and the first FAQ
answer explains that the figure is computed from the database rather than written
into the page. `NewBuild.tsx:281` still says "Typical run is 3-8 minutes" — that is
an app screen and was out of this plan's scope, but it is the same claim.

### What is new on the page

| Section | Data behind it |
|---|---|
| Prompt preview (§3) | The real `PromptComposer`. Text carries to `/build` via router state |
| Stage-card artifacts | `top_app_types` and `average_review_score` from `/stats`; a fixed deliverables list |
| Agent topology SVG | Static — 9 nodes and the conditional repair branch. `components/landing/AgentTopology.tsx` |
| Key pool | `health.llm.keys[]` — real count, real per-key state |
| Hero health footer | `worker_pool`, `groq_keys_available/total`, `llm.status` |
| Recent builds feed | `useBuilds()` → the real `BuildCard`, last 5, failures included |
| Analytics | `StatusBreakdown` + four figures; absorbed the old `Proof` rail |

### Three decisions worth keeping

1. **`ChartFrame` and `StatusBreakdown` moved to `components/charts/frame.tsx`.**
   Both are pure DOM and CSS, but `charts/index.tsx` imports Recharts at the top
   level, so importing either one from Landing would have pulled the whole library
   into the entry chunk. `charts/index.tsx` re-exports them, so no call site changed.
   **Entry chunk went 147 → 150.94 kB gzip.** A jump toward ~250 kB means Recharts
   leaked back in.
2. **Key suffixes are not rendered.** `/health` returns the tail of each live API
   key. The card shows `Key 01…Key 08` with real states instead: the argument —
   this many keys, this many holding quota — survives the redaction intact, and the
   page does not publish fragments of live credentials.
3. **Empty means absent, not skeletal.** With no builds, the feed renders nothing
   at all and the analytics block does not appear; the proof rail falls back to em
   dashes. Verified against a mocked-empty `/stats` and `/projects`.

### Verified
- typecheck / lint / 191 Vitest / `npm run build` — all clean.
- Landing at 1440×900 in three data states (populated, empty, `/health` blocked):
  **0 axe violations, 0 console errors, no horizontal overflow** in each.
- Prompt hand-off asserted end to end: typing on `/` and pressing the button lands
  on `/build` with the composer prefilled; an empty field carries nothing.
- The no-loop law holds — the only infinite animation on the page is the hero
  StepTracker's in-flight spinner, which is the sanctioned exception.

### The E2E suite is green again — and why it was not

Two `motion.spec.ts` tests were failing (route-transition residual opacity, and
the sidebar rail). They failed on the committed baseline too, so they were not
caused by the landing work — but they were **not** the test-timing flakes they
looked like. They were the same defect as §2.8: animations that never completed
left Framer with pending work, so the route wrapper really was still mid-opacity
when the test sampled it. Fixing the exit deadlock fixed both.

**79 pass, 1 skips, 0 fail**, stable across three consecutive full runs.

## 2.8 The dashboard status filter was dead — root cause and fix (most recent work)

Reported after the landing work and **present in `48d3ae7`**, so it predates it.
Clicking any status chip left all fifty rows of every status on screen.

### Everything upstream of the DOM was correct
The chip fired, `useBuilds(filter)` requested `?status=failed`, the backend
returned exactly the seven failed builds, and the component re-rendered with
them — instrumented and confirmed: `{filter:"failed", n:7, first:"failed"}` while
the DOM still held 50 rows. The count pill beside the chips even updated to
"7 builds", because it sits outside the list's `AnimatePresence`.

### The cause
`Dashboard.tsx` gave the list wrapper `exit="exit"`. That is a variant **label**,
and Framer propagates a label down the entire variant subtree — so all fifty
`BuildCard` rows began their own exit animation. Those per-row exits stall partway
(the rows carry `layout`, and the projection freezes their value animations while
the subtree is being removed; measured: parent reached `opacity: 0`, the last row
reached `0`, the first row sat at `1` forever). The wrapper's exit therefore never
reported completion, and the enclosing `AnimatePresence mode="wait"` waited on it
indefinitely: the outgoing list was never removed and the incoming one was never
mounted.

Without `mode="wait"` the same defect showed differently — the stale list *and*
the new list *and* the loading skeletons all stacked in the DOM at once.

### The fix
`lib/motion.ts` — `appStagger()` no longer carries an `exit` variant (it was the
trap), and exports **`appListExit`**, an explicit prop object. `Dashboard.tsx`
uses `exit={appListExit}` on both list wrappers, so the exit stays on the wrapper:
one opacity animation, one completion, ~90ms. That is also the correct motion
call — fifty rows leaving one after another is a 750ms wipe, well past the
≤120ms exit budget.

Every other `exit="exit"` in the app was audited: they all sit on single elements
using `disclose` or `popIn`, with no staggered children, and are unaffected.

### The guard
`e2e/integration.spec.ts` → "the dashboard status filter": five tests asserting
that every badge visible after a filter click is that status, and that exactly one
`.dash-results` is mounted. **Verified to fail when the bug is reintroduced** —
all five go red on `exit="exit"`.

Its first version was itself wrong in an instructive way: it polled
`count() <= before`, which the *stale* list satisfies on the first sample, so it
passed alone and failed under a loaded parallel run. It now polls the assertion
itself — the set of statuses actually on screen.

### Not fixed, deliberately
Each filter is its own react-query key, so switching filters has no cached data
and flashes the loading skeletons before the rows arrive. `placeholderData:
keepPreviousData` on `useBuilds` would remove the flash. It is a separate UX
change touching a hook Landing also uses, so it was left out of a bug fix.

## 3. What is NOT done

### 3.0 ~~Blocker~~ RESOLVED — `.gitignore` was hiding `frontend/src/lib/`

> **Fixed in `48d3ae7`.** `lib/` was anchored to `/lib/`, the UTF-16 corruption on
> the final line was repaired, and all six `frontend/src/lib/*` files are committed
> and pushed. The rest of this section is kept as the record of what was wrong.

The root `.gitignore` carried a Python
packaging rule at line 57:

```gitignore
lib/
```

It is unanchored, so it matches **any** directory named `lib` at any depth —
including `frontend/src/lib/`. Confirm it yourself:

```bash
git check-ignore -v frontend/src/lib/motion.ts
# .gitignore:57:lib/   frontend/src/lib/motion.ts
```

That directory has **never been committed**, and it holds `motion.ts` (which
every animated component now imports), plus `pricing.ts`, `scores.ts` and
`prompt.ts`. A fresh clone does not build. The directory is invisible to plain
`git status` — you need `git status --ignored` to see it at all, which is why
it went unnoticed across several sessions.

Two candidate fixes, both one line — **the choice is the maintainer's**, which
is why it was left undone:

```gitignore
/lib/                     # anchor it to the repo root (matches Python intent)
# — or —
!frontend/src/lib/        # negate it for the frontend specifically
```

Anchoring is the cleaner of the two: the rule came from a Python packaging
template and was only ever meant to match a build artefact at the root.

### 3.1 Everything else

1. **The landing restructure is not committed.** It sits in the working tree
   (`git status`: Landing.tsx, landing.css, NewBuild.tsx, charts/index.tsx, plus
   the new `charts/frame.tsx` and `components/landing/`). Review and commit is
   the obvious next step. Everything before it is committed as `48d3ae7`.
2. **`chromadb` and `langchain` are declared in `requirements.txt` and never
   imported.** Verified: "chromadb" occurs twice, both as a *string* and both
   about **generated** projects, not this app — `_HEAVY_IMPORT_PACKAGES` in
   `tools/code_executor.py` (an import-timeout heuristic) and a name→pip-spec
   map in `tools/requirements_builder.py`. "langchain" appears nowhere in the
   Python source at all. There is no `import chromadb` or `import langchain`
   anywhere. They pull in torch, pillow, nltk, gitpython and ecdsa, which
   account for **all 66 remaining venv CVEs**. Deleting the two lines from
   `requirements.txt` takes the Python audit to zero. Not done: it is a
   dependency change outside the plan's scope and wants a clean reinstall to
   confirm.
3. **Landing has no real images.** `design-taste-frontend` flags a text-only
   marketing page as incomplete. No image-generation tool was available, and
   inventing stock photography for a developer tool would be worse than the gap.
4. **Only Chromium** is in the Playwright matrix.
5. **Token pricing is hardcoded** in `lib/pricing.ts` ($0.59/$0.79 per 1M). The
   API sends no pricing field. One module now, so it cannot drift between
   screens, but still an assumption.
6. **`dist/` is current** as of the landing restructure — `npm run build` was
   the last thing run against it. Rebuild after any further source change if you
   use the one-command path at :8000.

7. **The skeleton flash on filter change** is unfixed by choice — see §2.8.

---

## 4. Traps — read before debugging anything

| Symptom | Cause |
|---|---|
| `127.0.0.1:5173` refuses to connect | Vite is IPv6-only here. Use `localhost`. |
| `/stats` or `/projects/{id}` blank in dev, 404 on `/assets/index-*.js` | The proxy forwarded an HTML navigation to the backend, which returned the **built** index.html whose asset hashes don't exist on the dev server. Fixed via `SPA_ROUTE_PREFIXES` in `vite.config.ts`; check that if it recurs. |
| A CSS class was pruned and nothing failed | Typecheck, lint, build and component tests all stay green on a dangling class. `src/test/classes.test.ts` catches it. It strips CSS comments first — the first version was fooled by the comment explaining the removal. |
| A control has no focus ring | `.composer__input`'s outline is suppressed **only** under `.panel`, because the panel's border is the indicator. Rendering the composer without one previously left zero focus indication in the rebuild dialog. |
| Backend dies on import | You used system Python. Use `venv/Scripts/python.exe`. |
| A file under `frontend/src/lib/` never shows in `git status` | The root `.gitignore`'s unanchored `lib/` rule swallows it. See §3.0. `git status --ignored` reveals it. |
| A reduced-motion E2E test passes but proves nothing | `test.use({ reducedMotion: 'reduce' })` did **not** reach the page here — `matchMedia` returned `false`. Use `page.emulateMedia({ reducedMotion: 'reduce' })`, and assert the query is actually on first. |
| An animation "looks broken" only under reduced motion | It probably is not. Check the emulation is real before touching the animation — see the row above. |
| A `layoutId` assertion fails by 1–2px at random | You sampled a mid-flight frame. Layout springs take longer under a loaded parallel run; poll to settlement rather than measuring once. |
| A `height: auto` disclosure collapses to a sliver, not to nothing | The animated element has its own padding/border. A border-box element at `height: 0` still paints them. Animate a bare wrapper instead (`.nb-error-slot`, `.pd-logs__reveal`). |
| E2E fails with connection errors | The backend isn't running. Playwright starts Vite but deliberately not the backend (it owns a DB and worker pool). |
| A list ignores a filter: the request is right, the response is right, React re-renders with the right rows, and the DOM keeps the old ones | `exit="exit"` on an `AnimatePresence` child that holds many `variants` children. The label propagates to every child, those exits stall, the wrapper's exit never completes, and `mode="wait"` waits forever. Use an **object** (`exit={appListExit}`). See §2.8. |
| An animation elsewhere "settles late" for no reason | A stalled exit anywhere leaves Framer with work that never completes. Two `motion.spec.ts` tests failed for months on exactly this and looked like sampling flakes. |
| A UI test passes while the screen is visibly wrong | It asserted the component's inputs, not the rendered DOM. The filter guard in `integration.spec.ts` asserts the badges actually on screen, and was checked to fail when the bug is put back. |

---

## 5. Locked decisions — do not re-roll

These survived four skill passes. Where a skill disagreed, the locked decision
won; the conflicts are recorded in `FRONTEND_REDESIGN_HANDOFF.md` §10 so they
are not "fixed" by a later session.

- **Archetypes**: Ethereal Glass (`#050507`, radial mesh, hairline borders) +
  Asymmetrical Bento.
- **Type**: Geist / Geist Mono / Instrument Serif italic accent.
- **Palette**: the CVD-validated chart palette. Blue stays out, violet is the
  brand, `cancelled` stays achromatic. Do not re-derive.
- **Motion**: Landing may be polish-forward. App screens get restraint —
  sub-200ms or nothing, and nothing loops except the in-flight spinner. This is
  now *implemented*, not just stated: `lib/motion.ts` is split into a marketing
  half and an app half, and §2.6 lists what moves on each surface. Import from
  there rather than hand-writing a transition.
- **Surfaces**: one class, `.panel`, at `--radius-lg`. Flat on app screens by
  design: blur on a scrolling column repaints every frame.
- **Icons**: `lucide-react`, one family, used consistently.

`--text-tertiary` was changed this session from `#55555F` to `#80808B`. That was
not taste: the old value measured **2.57:1** against the elevated surface, so
every mono micro-label in the system failed WCAG AA. The new value is 4.93:1
worst case and is the smallest step that clears 4.5:1 on all three backgrounds.

---

## 6. Useful live fixtures

| build_id | status | exercises |
|---|---|---|
| `fb3e4b24-5491-4925-bdb2-4a096df4735f` | `done_with_context` | handoff banner, scores, tokens |
| `fa7533e1-26bc-4ce6-9f0f-502d823e6632` | `failed` | failure path |
| `d715e3f9-ac30-4d62-947c-97976c75d87e` | `cancelled` | the "Build complete" bug that was fixed |

The DB currently holds 50 builds: 21 done, 17 cancelled, 7 failed, 4 running,
1 done_with_context. The running ones exercise the live WebSocket spine.

---

## 7. Where the new code lives

```
frontend/src/
  styles/app-shell.css          the app-side design system (.panel/.ulabel/.figure/.meter/.chip/.empty)
  components/shared/
    PromptComposer.tsx/.css     the ONE prompt field — NewBuild and RebuildModal share it
    StatTile.tsx/.css           the ONE KPI tile — Dashboard and Statistics share it
    RebuildModal.tsx/.css       rewritten; was 437 lines with 260 of injected CSS
  components/landing/
    AgentTopology.tsx           the pipeline as a shape: 9 nodes + the repair branch
  components/charts/
    frame.tsx                   ChartFrame + StatusBreakdown, Recharts-free on purpose
  components/layout/
    MobileBar.tsx/.css          the <900px top bar; drawer toggle lives here
  hooks/
    useFocusTrap.ts             shared by the modal and the drawer
    useMediaQuery.ts            useSyncExternalStore; no setState-in-effect
  lib/                          ⚠ CURRENTLY GITIGNORED — see §3.0
    motion.ts                   the motion vocabulary; marketing half + app half
                                `appListExit` — read §2.8 before using exit="exit"
    prompt.ts                   the 2000-char contract + readout state machine
    scores.ts                   one interpretation of the three score formats
    pricing.ts                  token rates, formatting, cost
  test/
    harness.tsx                 renderPage() + API-shaped fixtures
    classes.test.ts             every className cross-checked against the stylesheets
frontend/e2e/                   layout / a11y / integration specs + helpers.ts
  motion.spec.ts                animations verified as behaviour — see §2.6
```
