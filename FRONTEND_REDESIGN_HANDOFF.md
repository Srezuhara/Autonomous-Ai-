# Frontend Redesign — Handoff

## Status Report | Last Updated: August 25, 2026

**Read this first in a new session.** It carries the design decisions, the
verified commands, and the traps that cost time last session.

---

## 0. Start here — the 60-second version

| | |
|---|---|
| **Goal** | Redesign the frontend so it does not look like a generic AI build, using motion.dev + bklit + 21st.dev, 2-D only, without lag. |
| **Hard constraint** | **Frontend only.** The backend (`agents/`, `api_platform/`, `tools/`, `*.py`, `prompts/`) must not be modified. Last session verified this held. |
| **Done** | Design-token foundation, motion system, shared primitives, Landing (full rebuild), Statistics charts (full rebuild), 3-D removal. |
| **Next** | `NewBuild`, `BuildProgress`, `ProjectDetail`, `Sidebar`, `FloatingStatus` — these only inherit tokens, they were never restructured. |
| **Open decision** | Whether to install the *actual* bklit / 21st.dev components (see §7). |

---

## 1. Environment — verified commands

> [!IMPORTANT]
> **Run Vite on port 5173.** The backend's CORS allow-list is
> `["http://localhost:5173", "http://localhost:3000"]` and **must not be
> edited**. Last session started Vite on 5199, every API call was blocked, and
> the dashboard showed "Backend Unreachable" / empty charts — which looked like
> a frontend bug and was not.

```bash
# Frontend dev server — the port is not optional
cd frontend && npm run dev -- --port 5173 --strictPort

# Backend (read-only; never edit its source). Needs the venv — the system
# Python lacks `rich` and dies on import.
venv/Scripts/python.exe start_server.py       # serves :8000

# Typecheck / production build
cd frontend && npx tsc -b && npm run build
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
frontend/src/styles/primitives.css    bezel, eyebrow, CTA, ambient mesh, section
frontend/src/styles/landing.css       landing-only layout
frontend/src/lib/motion.ts            easings, durations, variants, viewport presets
frontend/src/components/ui/primitives.tsx   <AmbientMesh> <Bezel> <Eyebrow> <CTA> <Reveal>
frontend/src/components/charts/       chart components + charts.css
```

Build new screens **out of these primitives.** Do not invent a second card style.

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

### 5.3 3-D removed

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

---

## 7. Next steps

### Step 1 — Decide the bklit / 21st.dev question (blocks nothing, but answer it)

Last session did **not** install components from either site. Both are
shadcn-style registries requiring `npx shadcn init` first (there is no
`components.json` in this project). bklit is Recharts-based and Recharts was
already a dependency, so the charts were built to their design language using the
`dataviz` methodology instead.

**This is a real deviation from the literal request.** Either:
- **(a)** accept the current Recharts implementation, or
- **(b)** run `npx shadcn@latest init`, add the `@bklit` registry to
  `components.json`, and install real components:
  ```json
  { "registries": { "@bklit": "https://ui.bklit.com/r/{name}.json" } }
  ```
  ```bash
  npx shadcn@latest add @bklit/area-chart
  ```
  Note this pulls its own component files and dependencies and will need
  reconciling with the existing `components/charts/` and the token system.

### Step 2 — Redesign the remaining app screens

These currently **inherit the new tokens only** — they look consistent but were
never restructured. Use `/redesign-existing-projects` plus `/ui-ux-pro-max`, and
build from the existing primitives.

| File | Notes |
|---|---|
| `pages/NewBuild.tsx` (138 ln) | The prompt entry form — the highest-intent screen in the product. Deserves the most care. |
| `pages/BuildProgress.tsx` (249 ln) | Live 9-step progress + WebSocket logs. **Emil weighting — restraint.** Do not animate per-log-line; it updates constantly. |
| `pages/ProjectDetail.tsx` (520 ln) | Largest remaining file. Scores, files, download, rebuild. |
| `components/layout/Sidebar.tsx` | Works, but is the last obviously stock element. |
| `components/layout/FloatingStatus.tsx` | The "Backend Online" pill. |

**Apply the frequency gate before adding any motion to these** — they are
high-frequency surfaces, and the honest answer is often no animation at all.

### Step 3 — Verify

1. `npx tsc -b && npm run build` — must stay clean.
2. Screenshot each screen at 1440 and ~560 (see §1 caveat).
3. Check `prefers-reduced-motion` — the global kill-switch is in `tokens.css`,
   and Framer reads the same query.
4. Confirm `git status` shows **no** backend files.

---

## 8. Known gaps / honest state

- **Only Landing and Statistics were redesigned.** Four screens plus the sidebar
  remain stock-shaped.
- **bklit and 21st.dev components were never installed** (§7 Step 1).
- **The design skills were never actually invoked** — their content was read from
  disk. A new session applying them properly may reach different (better)
  conclusions on the remaining screens; the archetypes in §3 are the constraint
  to stay consistent with.
- Bundle is **816 kB / 249 kB gzip**, dominated by React + Recharts + Motion. Not
  addressed. If it matters, route-level `React.lazy` on Statistics would move
  Recharts out of the initial chunk.
- The daily-builds series has **one non-zero day in fourteen**, so the trend
  chart legitimately shows a single column. It is not broken.
- `prefers-reduced-motion` is implemented but was **not** verified in a real
  reduced-motion browser session.

---

*Frontend Redesign · Landing + Statistics complete · backend untouched · build clean*
*Workspace: `c:\programes\comppython\Aiautonomous`*
