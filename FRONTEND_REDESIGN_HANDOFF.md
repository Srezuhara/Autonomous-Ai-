# Frontend Redesign — Handoff

## Status Report | Last Updated: August 25, 2026 (completion pass)

**Read this first in a new session.** It carries the design decisions, the
verified commands, and the traps that cost time last session.

---

## 0. Start here — the 60-second version

| | |
|---|---|
| **Goal** | Redesign the frontend so it does not look like a generic AI build, using motion.dev + bklit + 21st.dev, 2-D only, without lag. |
| **Scope, as of this session** | No longer frontend-only. `FRONTEND_COMPLETION_PLAN.md` authorised four additive backend changes; all four landed and all four Python suites still pass. `agents/`, `tools/`, `prompts/`, `runner.py` and the DB schema remain untouched. |
| **Done** | Every screen is on the design system. All eight live bugs fixed. One surface vocabulary. Test suites exist where there were none: **191 Vitest** + **62 Playwright/axe**. |
| **Next** | Three Phase 4 skill passes were deferred (`design-taste-frontend`, `ui-ux-pro-max`, `high-end-visual-design`). See §9. |
| **Open decision** | bklit / 21st.dev was **resolved as (a)** — keep the Recharts implementation. See §7. |

---

## 1. Environment — verified commands

> [!IMPORTANT]
> **Use `localhost`, not `127.0.0.1`, for the dev server.** Vite binds to
> whatever `localhost` resolves to, which on this machine is IPv6 `::1` **only**
> — `http://127.0.0.1:5173` is refused at the socket, before any app code or
> CORS check runs. Measured this session. `npm run dev -- --host` binds both
> (and exposes the server on your network).

> [!NOTE]
> **The CORS trap is gone.** The dev server now proxies the API, so requests are
> same-origin and the port no longer matters for API access. `--strictPort` is
> still used because silently landing on 5174 hides configuration drift.

```bash
# Frontend dev server
cd frontend && npm run dev -- --port 5173 --strictPort

# Backend. Needs the venv — the system Python lacks `rich` and dies on import.
venv/Scripts/python.exe start_server.py       # serves :8000

# One command for the whole product: build the SPA, then start the backend,
# which serves it from the same origin at :8000.
cd frontend && npm run build && cd .. && venv/Scripts/python.exe start_server.py

# Verify
cd frontend
npm run typecheck && npm run lint && npm run build
npm run test        # 191 Vitest
npm run test:e2e    # 62 Playwright + axe — needs BOTH servers up

# Backend suites (test_phase17 needs the server running)
venv/Scripts/python.exe test_phase17.py
venv/Scripts/python.exe test_phase21.py
venv/Scripts/python.exe test_phase22.py
venv/Scripts/python.exe test_groq_rate_limit_handling.py
```

**Screenshotting (this exact invocation works on this machine):**

```bash
"/c/Program Files/Google/Chrome/Application/chrome.exe" \
  --headless=new --disable-gpu --hide-scrollbars \
  --window-size=1440,1400 \
  --screenshot="$(cygpath -w /path/to/out.png)" \
  --virtual-time-budget=8000 \
  "http://localhost:5173/"
```

> [!WARNING]
> **Chrome's `--window-size` is not the CSS viewport on this machine.** Asking
> for `390` produced a **506px CSS viewport** written into a 390px-wide image,
> so the page *looked* clipped when nothing was wrong. Do not diagnose
> responsive bugs from a screenshot alone — measure
> `document.documentElement.scrollWidth` vs `clientWidth`. The narrowest
> reliable capture is ~560px.

---

## 2. Skills — the reason to start a new session

21 skills were installed to `C:\Users\KIIT0001\.claude\skills\`, but a session
only builds its skill list at startup, so last session **could not invoke them**
— their content was read off disk manually instead. **In a new session they load
as slash commands.**

Most relevant to the remaining work:

| Skill | Use for |
|---|---|
| `/design-taste-frontend` | The main anti-generic frontend skill |
| `/high-end-visual-design` | Agency-tier spacing, shadows, card architecture (drove most of §3) |
| `/design-motion-principles` | Motion — Create vs Audit modes |
| `/ui-ux-pro-max` | UI/UX review of the app screens |
| `/redesign-existing-projects` | Upgrading screens without breaking them — **fits the remaining pages exactly** |
| `/dataviz` | (bundled, already worked) chart form + palette validation |

Seven skills that need image-generation or other agents were parked in
`~\.claude\skills-unavailable\` with a README explaining each.

> [!NOTE]
> **The app-screen pass did not invoke them either.** The archetypes in §3 were
> already locked and the job was to stay consistent with them, so the work was
> driven from §3 + §4 directly rather than re-deriving direction from
> `/design-taste-frontend` or `/redesign-existing-projects`. If a future session
> wants a genuinely independent design read — on `Dashboard`, say — invoking
> them is still untried.

---

## 3. Design decisions already made — do not re-roll these

The `high-end-visual-design` skill asks you to pick archetypes. **They are
picked. Stay consistent with them:**

- **Vibe archetype: Ethereal Glass** — near-black OLED base (`#050507`), radial
  mesh orbs, vantablack cards with hairline borders.
- **Layout archetype: Asymmetrical Bento** — no centred, equal-width 3-column
  grids anywhere.
- **Motion weighting is split by surface** (from `design-motion-principles`):
  - **Landing → Jakub/Jhey.** Polish-forward, 300–700 ms, heavy `--ease-glide`.
  - **Dashboard/app → Emil.** Restraint. Sub-200 ms or *no* motion. These screens
    are hit hundreds of times a session; motion there is friction.

**Typography (locked):** `Geist` UI · `Geist Mono` numerals/labels ·
`Instrument Serif` *italic* accent used on **one or two words per page, never
more**. Inter is banned by the skill and was removed.

**Files that define all of this:**

```
frontend/src/styles/tokens.css        design tokens (single source of truth)
frontend/src/styles/primitives.css    LANDING vocabulary — bezel, eyebrow, CTA, ambient mesh
frontend/src/styles/app-shell.css     APP vocabulary — panel, page-head, ulabel, figure,
                                      meter, chip, keycap, sdot, toolbar
frontend/src/styles/landing.css       landing-only layout
frontend/src/lib/motion.ts            easings, durations, variants, viewport presets
frontend/src/components/ui/primitives.tsx   <AmbientMesh> <Bezel> <Eyebrow> <CTA> <Reveal>
frontend/src/components/charts/       chart components + charts.css
```

Build new screens **out of these primitives.** Do not invent a second card style.

> [!IMPORTANT]
> **Two vocabularies, one system.** `primitives.css` is for the *landing*;
> `app-shell.css` is for the *product screens*. They share tokens, hairlines and
> the inset highlight, so they read as one design — but the app layer is
> deliberately lower-energy: no glide easing, no scroll reveals, no lift-on-hover.
> `<Bezel>` is the landing's container; `.panel` is its flat app-side sibling.
> `.card` is now a retuned alias of `.panel`, kept only so unconverted screens
> keep resolving.
>
> **Never put `backdrop-filter` on a scrolling surface.** `.card` carried
> `blur(20px)` while living inside `.main-content`, which scrolls — that forces
> the compositor to re-sample the backdrop every frame. Blur is only used on
> `.sidebar` and `.fstatus`, both of which are fixed/sticky.

---

## 4. The validated chart palette — do not re-derive

Produced with the `dataviz` validator against the dark surface `#0E0E14`.
**Four attempts failed before this passed** — reuse it rather than re-running the
search:

| Token | Hex | Role |
|---|---|---|
| `--viz-done` | `#0E9F6E` | good |
| `--viz-degraded` | `#C07E14` | warning |
| `--viz-running` | `#7C6BFA` | brand accent |
| `--viz-failed` | `#F43F5E` | critical |
| `--viz-cancelled` | `#5A5A66` | **neutral, deliberately achromatic** |
| `--viz-seq` | `#7C6BFA` | sequential single hue |

Why the failures matter, so they are not repeated:

- Bright brand colours (`#34D399` etc.) sit at OKLCH **L 0.71–0.80** — outside
  the dark band (**0.48–0.67**). They must be stepped down for a dark surface,
  not reused from the light UI palette.
- **Blue and violet cannot coexist** — `#3B82F6` vs `#7C6BFA` scored ΔE **0.7**
  (deutan) and 8.4 normal-vision. Violet is the brand, so blue was dropped.
- **`cancelled` is grey on purpose.** A user-stopped build is not an error;
  making it achromatic also removed a hue from the adjacent pairlist, which is
  what finally let the remaining four pass CVD. `StatusBadge.tsx` was aligned to
  match — keep the badge and the chart telling the same story.

Re-validate with:

```bash
cd "C:/Users/KIIT0001/AppData/Local/Temp/claude/bundled-skills/2.1.241/6751f8dd2a9a84ea52d89867bca0af80/dataviz"
node scripts/validate_palette.js "#0E9F6E,#C07E14,#7C6BFA,#F43F5E" --mode dark --surface "#0E0E14"
```

---

## 5. What was actually done

### 5.1 Landing — rebuilt

The old page ran a **Spline 3-D scene and a WebGL fragment shader**, both
looping `requestAnimationFrame` for the entire session, and painted the page in
hardcoded browns (`#2C1810`) and gold (`#FFD700`) that fought the indigo tokens.

Replaced with `<AmbientMesh>` — three fixed radial gradients plus a grain layer.
**One paint, then zero runtime cost.** Sections: hero (editorial split) → agent
rail → how-it-works bento → feature bento → proof rail → FAQ (sticky-rail split)
→ closing CTA.

### 5.2 Statistics — charts rebuilt

Forms were chosen **before** colour, per `dataviz`:

| Chart | Before | Now |
|---|---|---|
| Build volume | area, 2 series | **columns**, 1 hue — daily counts are sparse discrete events; an area with one active day in fourteen collapses to an invisible flat line |
| Build outcomes | "Success vs Failed" that **re-plotted the same daily series as the chart above it** | part-to-whole stacked bar of `by_status` + value table |
| App types | pie that **rendered nothing** | horizontal bars, sorted, direct value labels |
| Token split | meter | unchanged — already the correct form |

### 5.3 App screens — restructured (this session)

A shared `styles/app-shell.css` layer was added first, then every remaining
screen was rebuilt on it. Structure changed, not just tokens.

| Screen | What actually changed |
|---|---|
| `NewBuild` | Was a single centred column where the textarea, the keyboard hint and a 2x2 grid of example cards all competed at the same width. Now an asymmetric split: an accent composer (label + field + budget meter + action bar as **one instrument**, no inner boxes) against a fixed 312px pipeline rail that previews the nine real agent names. Examples demoted from cards to chips. The char counter became a state readout — `"7 more characters to start"` answers the question the user actually has, which `"1847 chars left"` does not. |
| `StepTracker` | Rewritten as a spine. The rail is a per-row full-height `::before` at the marker's x-position, so it reads continuous but each segment colours from its own step — see §6 for why the two obvious alternatives fail. Markers are opaque discs that mask the rail behind them. One row is ever emphasised (the running one); done recedes, pending dims. |
| `BuildProgress` | Spine + status column. Both looping `pulse` animations on the connection pill deleted. The build id moved from a body-scale line under the H1 to a mono kicker above it. The "while you wait" bullet prose became a definition list with real figures. Advisory cards unified into one `.bp-note` shape (they were three variants built from inline styles). |
| `ProjectDetail` | Was eight equally-weighted cards stacked vertically — a timestamp had the same visual weight as the review score. Now three tiers: header (identity + horizontal action toolbar + prompt as a quotation + mono timing strip), readout (scores in one panel divided by hairlines; tokens likewise), evidence (logs + file tree, flush-edged). File tree dims the directory prefix so a 60-file build is scannable by filename. |
| `Sidebar` | "New Build" promoted out of the nav list into a pinned primary button — it is the product's only verb and it was sitting as a peer of Dashboard. Active state is a rail indicator, not a filled pill. The gradient-chip logo became a hairline plate. |
| `FloatingStatus` | Collapsed by default: a static dot and one word. Expands to the full breakdown only when something needs attention, or on hover. `dot--error` was **missing from the stylesheet entirely**, so the one state that blocks builds rendered with no colour; it now uses the shared `.sdot` scale. |
| `StatusBadge` | `running` was a **Play triangle spinning on an infinite loop** — one loop per running build in the dashboard list. Now a static loader glyph. Also moved from `badge-info` blue to `badge-accent` violet, per §4: a blue "Running" badge beside a violet "running" chart segment tells two stories about one state. |

### 5.4 3-D removed

`splite.tsx` and `shader-animation.tsx` deleted; `three`, `@types/three`,
`@splinetool/react-spline`, `@splinetool/runtime` removed from `package.json`.
Verified **0 occurrences** of Three/Spline in the production bundle.

---

## 6. Bugs found and fixed — the non-obvious ones

- **Recharts `layout="vertical"` needs the number axis bound explicitly.**
  Without `dataKey` + `domain`, every bar drew ~3px wide regardless of value.
  Fix: `<XAxis type="number" dataKey="value" domain={[0,'dataMax']} hide />`.
- **Recharts animates bars up from zero over ~1.5s.** They never settle in a
  headless capture, so charts screenshot empty. `isAnimationActive={false}` —
  correct for a dashboard anyway.
- **CSS import order is not guaranteed.** `landing.css` is imported from the
  component while `primitives.css` comes from `index.css`; at equal specificity
  the override silently lost and left a dead band under the hero. Fixed with
  `.section.agents` (doubled class), not by reordering imports. **Any future
  page-level override of a primitive needs the same treatment.**
- **`hyphens: none` does not stop a break at a hard hyphen.** "full-stack" split
  across lines at display size; fixed with U+2011 non-breaking hyphen.
- **`clamp()` floors matter as much as caps** — a `3rem` floor won on small
  viewports and overflowed. Now `2.25rem`.

**From the app-screen pass:**

- **A `grid-template-rows: 0fr` collapse needs exactly ONE clipping child.**
  `FloatingStatus`'s detail lines were direct children, so each became its own
  implicit row and only the first collapsed — the pill sat permanently
  half-open. Fixed with a `.fstatus__detail-inner` wrapper carrying both
  `min-height: 0` and `overflow: hidden`.
- **The step rail has two tempting wrong implementations.** A single absolutely
  positioned rail behind the list cannot colour per-step. A rail filled by
  *percentage of list height* drifts out of register with the markers the moment
  one row wraps to two lines. The working answer is a per-row full-height
  `::before` at the marker's x-position, terminated at the first and last marker
  with `top`/`bottom` offsets derived from a shared `--mark-center` custom
  property.
- **`.figure__unit` at `0.55em` needs a much larger `margin-inline-start` than it
  looks like it does** — the margin resolves against the *unit's* reduced font
  size, so `0.15em` rendered as roughly one pixel and produced `"5of 9"`. It is
  `0.6em` now.
- **`.spin-icon` was declared twice** — `BuildCard.css` at 1.4s and
  `FloatingStatus.css` at 0.8s — so the same "working" affordance span at
  different speeds depending on stylesheet order. It now lives once in
  `globals.css` beside `@keyframes spin`.
- **The page-level `max-width` override trap from above bit again.** Every page
  root that overrides `.page-wrapper` is written doubled
  (`.new-build.page-wrapper`, `.build-progress.page-wrapper`,
  `.project-detail.page-wrapper`). Keep doing this.

---

## 7. The bklit / 21st.dev question — resolved

**Decision: (a). Keep the Recharts implementation.** No shadcn registry was
initialised.

The reasoning, so it is not reopened by default: both are shadcn-style
registries that require `npx shadcn init` and a `components.json` this project
does not have. bklit is itself Recharts-based, and Recharts was already a
dependency. Installing it would pull its own component files, its own dependency
set, and its own token assumptions, all of which would then have to be
reconciled against `tokens.css` and the CVD-validated palette in §4 — which was
expensive to derive and passes. The charts were built to that design language
using the `dataviz` methodology instead, and they validate.

If a future session wants to revisit:

```json
{ "registries": { "@bklit": "https://ui.bklit.com/r/{name}.json" } }
```
```bash
npx shadcn@latest add @bklit/area-chart
```

Reconcile against `components/charts/` and the §4 palette before merging
anything it installs.

---

## 8. Verification — what was actually measured

The ad-hoc CDP probing the previous version of this section describes has been
replaced by committed suites. Everything below is a check that runs on demand,
not a one-off measurement.

**Static**

- `npm run typecheck` — clean across three TS projects (app / node / test).
- `npm run lint` — clean. Was 3 errors (`set-state-in-effect` x2, one since
  introduced and fixed).
- **`strict` is now ON.** It was absent from `tsconfig.app.json`, so
  `strictNullChecks` and `noImplicitAny` were off. Measured before enabling:
  the existing source produced **zero** errors under strict, so it cost nothing.

**Bundle** — route-level `React.lazy` on `Statistics` moved Recharts out of the
initial chunk:

| | before | after |
|---|---|---|
| initial JS | 820 kB / 250 kB gzip | **469 kB / 147 kB gzip** |
| Statistics chunk | — | 357 kB / 105 kB gzip (on demand) |
| CSS | 76 kB / 14 kB gzip | 63 kB / 11.5 kB gzip |

The >500 kB Vite warning is gone.

**Component tests — 191 across 11 files** (`npm run test`). Behaviour, not
snapshots: a snapshot would have passed happily through every bug this suite
exists to catch. Each guard was verified to actually fail when its bug is
reintroduced — checked explicitly for the `pending` badge and the dangling-class
check.

**E2E — 62 passing, 1 skipped by design** (`npm run test:e2e`, Chromium):

- Zero console errors and zero failed requests on all six routes.
- **No horizontal overflow** at 1440 / 1024 / 820 / 640 / 420, measured both by
  `scrollWidth` vs `clientWidth` *and* by scanning element rects — the latter
  now skips elements clipped by an `overflow: hidden` ancestor, which removed a
  false positive on the ambient mesh's deliberately off-canvas orbs.
- `prefers-reduced-motion` → **exactly 0** elements declaring motion, every route.
- **Exactly one infinite animation** app-wide, and only `spin`.
- Drawer: opens, traps focus across 8 tabs, Escapes, closes on navigation, and
  its scrim fades rather than being deleted.
- Keyboard traversal reaches every dashboard control with a visible focus ring.

**Accessibility — zero serious/critical axe violations** on all six routes plus
the open drawer and the open dialog. There was no a11y tooling before this pass.
It found one real defect: `--text-tertiary` was `#55555F`, measuring **2.57:1**
against the elevated surface, so every mono micro-label in the system failed
WCAG AA. Now `#80808B` — **4.93:1** worst case, the smallest step that clears
4.5:1 against all three backgrounds while staying recessive.

**Integration** — a contract test asserts every path in `api/client.ts` exists
on the running backend; `DELETE /projects/cleanup` is reachable; the 2000-char
limit matches on both sides; and `/projects/{id}` returns the SPA to a browser
navigation while still returning JSON to `fetch`.

**Backend** — all four Python suites re-run after the four backend edits:
`test_phase17` 54/54, `test_phase21` 77/77, `test_phase22` 85/85,
`test_groq_rate_limit_handling` OK.

---

## 9. Known gaps / honest state

Everything the previous version of this section listed has been closed:
Dashboard is restructured, mobile navigation exists, the bundle is split, the
pricing constants are in one module, `.card` is deleted rather than aliased,
and all four Phase 4 skill passes have now run. What remains:

- **`chromadb` and `langchain` are declared in `requirements.txt` and never
  imported.** Verified: the only occurrence of "chromadb" in the codebase is a
  string inside `_HEAVY_IMPORT_PACKAGES` in `tools/code_executor.py`, a
  heuristic about *generated* projects. "langchain" appears nowhere at all.
  Between them they pull in torch, pillow, nltk, gitpython and ecdsa, which
  account for **every one of the 66 CVEs remaining in the venv**. Removing the
  two lines would take the Python audit to zero. Not done here: it is a
  dependency change outside this plan's scope and wants a deliberate
  `pip install -r requirements.txt` from clean to confirm.
- **Token pricing is still an assumption.** `lib/pricing.ts` holds the
  $0.59 / $0.79 per-1M rates in one place instead of two, but the API sends no
  model or pricing field, so the figures are hardcoded, just no longer able to
  drift between screens.
- **The E2E suite needs the backend started by hand.** Deliberate: it owns a
  database and a worker pool.
- **One E2E test spends real LLM quota** and is skipped by default. Run it with
  `E2E_LIVE_BUILD=1 npm run test:e2e`.
- **`prefers-reduced-motion` stops the spinner entirely.** Verified acceptable:
  every spinner has a text label beside it. Do not add one without.
- **Only Chromium is in the Playwright matrix.**
- **The Landing page has no real images.** `design-taste-frontend` flags a
  text-only marketing page as incomplete. No image-generation tool was
  available in this environment, and inventing stock photography for a
  developer tool would be worse than the gap. Left as a deliberate decision.

---

## 10. Skill conflicts with locked decisions

Phase 4 ran four skills against locked archetypes. Where they disagreed, the
locked decision won, as the plan requires. Recorded so the next session does
not "fix" these:

| Skill says | Locked decision | Why locked wins |
|---|---|---|
| `Instrument_Serif` is banned as an LLM-favourite display serif | Instrument Serif italic is the accent face | Named in the locked typography triple. It is used for single emphasised words, not as a display default, which is the usage the ban targets. |
| Lucide icons discouraged; use Phosphor / Radix / Tabler | `lucide-react` throughout | Swapping icon libraries across 11 components is a redesign, not refinement. One family is used consistently, which is the rule that actually matters. |
| "No element appears statically" / scroll entry everywhere | App screens get restraint: sub-200ms or nothing | Directly contradicts the motion contract these screens were rebuilt around, and the motion audit that verified it. Landing is polish-forward; the product is not. |
| Double-Bezel on all major cards; `rounded-[2rem]` | Flat `.panel` at `--radius-lg` on app screens | `.panel` exists precisely because blur on a scrolling column repaints every frame. Documented perf decision. |
| Section padding minimum `py-24` | App screens use the product spacing scale | A marketing-page rule applied to dense product UI. |
| Never animate layout properties | `.meter__fill` animates `width`; `.fstatus__detail` animates `grid-template-rows` | Considered and kept. `transform: scaleX()` distorts the fill's radius, and grid-rows is the only way to animate to an unknown auto height. Both are small, non-continuous, and inside clipped containers. |

`design-taste-frontend` also declares itself out of scope for dashboards and
dense product UI (its Section 13), so it was applied to Landing only.

---

## 11. New traps found this session

- **The Vite proxy and the SPA mount fought each other.** With `frontend/dist`
  present, navigating to `/stats` or `/projects/{id}` in dev was proxied to the
  backend, which returned the *built* `index.html` whose hashed asset URLs do
  not exist on the dev server. Blank page. Fixed by bypassing the proxy for
  requests that accept `text/html` (`SPA_ROUTE_PREFIXES` in `vite.config.ts`).
- **Pruning a CSS class does not fail anything.** `.empty-state` was removed
  from `globals.css` while `ProjectDetail` still referenced it; the state
  rendered unstyled and typecheck, lint, build and every test stayed green.
  `src/test/classes.test.ts` now cross-checks every `className` literal against
  the stylesheets, and strips CSS comments first, because the first version of
  that check was fooled by the comment explaining the removal.
- **A focus-ring suppression outlived its justification.** `.composer__input`
  had its outline removed on the grounds that its `.panel` surface lights up
  instead. True on NewBuild; the rebuild dialog rendered the same composer
  *without* a panel, so that field had border `0px`, no shadow and no outline:
  no focus indication at all. axe does not catch this. The rule is now scoped
  to `.panel .composer__input`, so the suppression cannot outlive the surface
  that justifies it, and an E2E test asserts focus indication in both contexts.
- **`127.0.0.1:5173` does not reach the dev server.** Vite binds to whatever
  `localhost` resolves to, which here is IPv6 `::1` only. The request is
  refused at the socket, before CORS or any app code. Use `localhost`, or
  `npm run dev -- --host`.

---

*Every screen on the design system · 8 live bugs fixed · 191 unit + 64 E2E tests · 216 backend assertions · 0 npm and 0 request-path Python CVEs*
*Workspace: `c:\programes\comppython\Aiautonomous`*
