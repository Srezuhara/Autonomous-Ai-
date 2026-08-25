# Landing Page Restructure — Approved Plan (desktop)

> **Status: EXECUTED — Phases 1, 2 and 3 all landed 2026-08-25.** Written and
> approved in the session that produced commit `48d3ae7`; executed in the next
> session. The working tree carries the change; it is not yet committed.
>
> This file is now the record of what was decided and why. **Do not re-run it.**
> What actually shipped, what deviated from the plan, and what was deliberately
> left out are all recorded in `SESSION_PROGRESS.md` §2.7.

## How to resume

```bash
# Backend — MUST be the venv interpreter (system Python lacks `rich`)
venv/Scripts/python.exe start_server.py            # :8000

# Frontend dev server, separate terminal
cd frontend && npm run dev -- --port 5173 --strictPort
```

Open **http://localhost:5173** — use `localhost`, never `127.0.0.1` (Vite binds IPv6 `::1` only
on this machine).

Related docs: `SESSION_PROGRESS.md` (current state), `FRONTEND_REDESIGN_HANDOFF.md` (locked design
decisions), `PHASE22_HANDOFF.md` (backend state). Scope here is **frontend only, desktop-first** —
no backend changes are needed or wanted.

---


## Context

The user supplied a 12-point UI execution plan to restructure the Landing page so it argues
for the product with **operational evidence** rather than marketing claims. This plan records
an assessment of that brief and the execution path agreed after four clarifying decisions.

Scope: **frontend only, desktop-first**. No backend changes — none are needed.

---

## Assessment of the brief

**Verdict: strategically right, roughly 85% executable as written. One systematic flaw, now resolved.**

### What it gets right

- **The central thesis** (§1, §5) — operational proof beats marketing claims — is correct, and
  is already this codebase's stated philosophy. `Landing.tsx:38-44` documents removing a
  hardcoded "18 Endpoints" precisely because it was "a hardcoded number presented as measurement".
- **§10 motion rules** are almost exactly the rules already encoded in `frontend/src/lib/motion.ts`.
  "Do not animate numbers continuously" matches the charts' deliberate `isAnimationActive={false}`.
  "Avoid infinite motion" matches the codebase's no-loop law. Well judged.
- **§11 visual rules** accurately describe the existing design system — violet for active/primary,
  status colours reserved for operational meaning, grain texture, nested radii tightening inward.
- **§5's insight** that showing failures builds trust is correct — and real data delivers it free.

### The systematic flaw (resolved)

The brief repeatedly asks for **fabricated** operational detail — a "believable mix" of builds,
`Key 02 active` on a rotation loop, `Estimated run: 6–9 min`, a fake telemetry log — in a codebase
with an explicit documented rule against exactly that:

> "A fake product UI assembled out of divs is the most recognisable tell in an AI-built landing
> page, and it carries a second cost: it drifts." — `Landing.tsx:190-208`

Every one of those data points is **already exposed by the running backend**. Decision taken:
wire them to real data. This makes the page more honest, non-drifting, and no more expensive.

### What the brief misses

1. **No empty-state handling.** A fresh instance has zero builds; all three new sections would be
   blank. `Proof()` already solves this with `PROOF_FALLBACK` — new sections need the same discipline.
2. **Chart bundle cost.** `Statistics` is the only lazy route (`App.tsx:22`) and its chunk is
   **356.97 kB (105 kB gzip)**, almost entirely Recharts. Landing sits in the 472.69 kB (147 kB gzip)
   entry chunk. Naively importing charts into Landing would add ~100 kB gzip to the marketing page.
3. **A real bug it doesn't catch.** `PIPELINE_AGENTS` (`Landing.tsx:52-61`) has **8** entries —
   Architect is missing — while the page claims "9-agent pipeline" in four places (eyebrow L112,
   hero stat L46, feature card L338, FAQ L91). Names also don't match the backend's canonical set.
4. **Hero density.** §2 wants per-agent metadata plus a health footer in a panel already scaled to
   `--preview-scale: 0.94` with timestamps hidden (`landing.css:96-122`) because it is dense at that
   size. Add the footer; add per-agent metadata sparingly.
5. **Page length.** 7 sections → 10. The existing 4-number `Proof()` rail overlaps heavily with the
   proposed §7 analytics block — **merge them** rather than shipping both.

### Already built (the brief treats these as new)

| Brief item | Reality |
|---|---|
| §2 hero split, headline, 2 CTAs, compact metrics, pipeline panel | Built, incl. staged 0.06/0.13/0.2s motion cascade |
| §4 four stage cards, asymmetric grid, cards 1 & 4 wider | Built (`landing.css:179-221`) |
| §6 large left card + two stacked right cards | Built exactly as described (`.bento__major` + 2 × `.bento__minor`) |
| §8 FAQ accordion, single-open, first open, + → × | Built (`Landing.tsx:441-499`) |
| §9 "Ready when you are" / "Start your first build" | Built (`Landing.tsx:505-531`) |
| §10 motion vocabulary | Built — `viewportOnce`, `liftable`, `disclose`, `MotionConfig reducedMotion="user"` |

Genuinely new: §3 prompt preview, §5 builds feed, §7 analytics, plus enrichment of §2/§4/§6/§9.

---

## Decisions locked

1. **Real data everywhere.** No fabricated builds, keys, or telemetry.
2. **Keep the no-loop rule.** Hero animates once on load, then rests.
3. **Wire the prompt preview for real** — typing on Landing carries through to `/build`.
4. **Phase it**, high-impact first.

---

## Phase 1 — proof sections

### 1.1 Fix the agent-count bug
`frontend/src/pages/Landing.tsx:52-61` — extend `PIPELINE_AGENTS` to 9 and adopt the canonical
names from `STEP_NAMES_FALLBACK` (`components/shared/StepTracker.tsx:47-57`): Intent Analyzer,
Planner, Architect, Backend Developer, Frontend Generator, Debugger, Reviewer, Tester, Documenter.
Needs one additional Lucide icon for Architect.

### 1.2 Recent builds feed (new section, after `Features`)
- Data: `useBuilds()` from `frontend/src/hooks/useQueries.ts` — no status arg, so it shares
  Dashboard's `['projects', undefined]` react-query cache. `.slice(0, 5)` client-side.
- Render with the existing **`BuildCard`** (`components/shared/BuildCard.tsx`) — real statuses,
  real scores, real durations, and it already links to the detail route.
- **Gotcha:** `listProjects` returns `total` = length of the returned page, not the global count
  (`api_platform/routes/projects.py:49-71`). Use `stats.total_builds` for a "View all N builds" link.
- Empty state: render nothing when there are no builds — do not show a skeleton on a marketing page.

### 1.3 Analytics block (new section — absorbs the existing `Proof` rail)
- **`StatusBreakdown({ byStatus: stats.by_status })`** — this is **pure CSS** (`.meter--split` +
  legend table), *not* Recharts, so it is free. Use it as the centrepiece.
- Figures from `/stats`: `total_builds`, `success_rate_percent`, `avg_duration_seconds`,
  `average_review_score`, `token_usage`. Cost via `costOf`/`formatCost` in `frontend/src/lib/pricing.ts`
  — label it "estimated at listed rates", as Statistics does.
- **Defer Recharts.** `AppTypeChart` / `BuildTrendChart` are Recharts and would land in the entry
  chunk. Either omit in Phase 1 or put them behind `lazy()` + a viewport boundary.
- Fold the current `Proof()` rail into this section rather than keeping both.
- Guard token figures on `total_tokens === 0 && avg_tokens_per_build === null` (pre-Phase-17 builds
  have no token data).

---

## Phase 2 — enrichment

### 2.1 Hero health footer
Real data via `useHealth()` (`frontend/src/hooks/useHealth.ts`) — `worker_pool.active/available`,
`llm.groq_keys_available`/`groq_keys_total`, `llm.status`. `useHealth` returns `null` rather than
throwing, so it degrades cleanly. Use the `.sdot--ok/--warn/--error` status dots from `app-shell.css`.

### 2.2 Stage cards — embedded UI fragments
Add one small real artifact per card in `STEPS`. Prefer reusing real components/classes
(`.meter`, `.figure`, `.ulabel`, `StatusBadge`) over hand-built div mock-ups, for the drift reason above.

### 2.3 §6 graphics
- **Agent topology**: inline SVG, 9 nodes, one repair branch. New file under
  `frontend/src/components/landing/`.
- **Multi-key rotation**: **real** — `health.llm.keys[]` gives `{ suffix, status }` per key. Show
  actual key suffixes and actual states. Better than the brief's fake rotation loop.
- **Telemetry**: derive from the most recent build's steps, or keep as prose. Do not fabricate a log.

### 2.4 Prompt-to-build preview
- Reuse **`PromptComposer`** (`components/shared/PromptComposer.tsx`).
- Wire it: `frontend/src/pages/NewBuild.tsx:75` currently hardcodes `useState('')`. Accept an initial
  prompt from router state (`useLocation().state?.prompt`) so Landing can `navigate('/build', { state })`.
  Frontend-only, ~3 lines.

---

## Phase 3 — copy and polish

- FAQ 5 → 7 entries, retargeted to risk/implementation questions per §8.
- Closing CTA delivery summary (repository / tests / docs) per §9.
- Motion consistency pass; confirm nothing loops and `viewportOnce` is used for one-shot reveals.

---

## Cross-cutting

**Motion weight.** Landing is marketing-weight (300–700 ms glide, `fadeUp`, blur resolve); `BuildCard`,
`StatTile` and the charts carry app-weight motion internally (≤180 ms, no blur). Dropping them in
creates deliberate dashboard-weight islands — which is what `PipelinePreview` already does. Keep the
island framed by a `Bezel` so the shift reads as intentional. Note `StatTile` only animates inside a
parent running `appStagger`; wrap tiles in `RevealItem` instead.

**Desktop-only.** Add a one-line single-column collapse for each new section inside the existing
`@media (max-width: 1023px)` block in `landing.css:434` so narrow viewports degrade rather than break.
No full mobile polish this pass.

---

## Files

| File | Change |
|---|---|
| `frontend/src/pages/Landing.tsx` | Agent list fix; new `RecentBuilds`, `Analytics`, `PromptPreview` sections; `Proof` absorbed; hero footer; FAQ/CTA copy |
| `frontend/src/styles/landing.css` | Styles for new sections + collapse rules in the existing media block |
| `frontend/src/pages/NewBuild.tsx` | Accept prefilled prompt from router state (Phase 2 only) |
| `frontend/src/components/landing/` | New — agent topology SVG |

Reused as-is, no changes: `BuildCard`, `StatusBadge`, `StatTile`, `PromptComposer`, `StepTracker`,
`ChartFrame`/`StatusBreakdown`, `useBuilds`/`useStats`/`useHealth`, `lib/pricing.ts`, `lib/motion.ts`,
`ui/primitives`.

---

## Verification

```bash
cd frontend
npm run typecheck        # tsc -b
npm run lint
npm run build            # WATCH the entry chunk — must stay ~147 kB gzip; a jump to ~250 kB means Recharts leaked in
npm run test             # 191 Vitest
npm run test:e2e         # 75 Playwright + axe — needs BOTH servers up
```

Both servers (backend on `:8000` via `venv/Scripts/python.exe start_server.py`, frontend on `:5173`)
are currently running. Visual check at 1440×900 on `http://localhost:5173` — use `localhost`, never
`127.0.0.1` (Vite binds IPv6 `::1` only here).

Data-state checks, since every new section is live:
- **Populated** (current instance, 50 builds incl. `done_with_context`) — feed and analytics render.
- **Empty** — stop the backend, or point at a fresh DB: sections must hide or show honest dashes,
  never a broken layout or a spinner that never resolves.
- **Backend down** — `useHealth` returns `null`; the page must still render.
- Confirm axe passes on the new sections (`e2e/a11y.spec.ts` covers `/`).
