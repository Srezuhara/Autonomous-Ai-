/**
 * pages/Landing.tsx — v4
 * ======================
 * Rebuilt 2D. The previous version rendered a Spline 3-D scene plus a WebGL
 * fragment shader, both running animation loops for the whole session, and
 * painted the page in hardcoded browns (#2C1810) and gold (#FFD700) that fought
 * the indigo design tokens. All of it is gone: the background is now static CSS
 * gradients and every colour resolves from a token.
 *
 * Layout archetype: Asymmetrical Bento. Nothing is a centred 3-column grid.
 * Motion weighting:  polish-forward (300-700ms glide) — this is the pitch
 *                    surface, unlike the dashboard where motion is restraint.
 */
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowRight, ArrowUpRight, Activity, FileText, Code, Server,
  CheckCircle2, Terminal, BarChart3, Database, Zap, TrendingUp,
  Plus, ShieldCheck, GitBranch, Layers, Coins, Gauge,
} from 'lucide-react';
import {
  AmbientMesh, Bezel, Eyebrow, CTA, Reveal, RevealGroup, RevealItem,
} from '@/components/ui/primitives';
import {
  fadeUp, fadeUpTight, appItem, appStagger, viewportOnce, EASE, DURATION,
} from '@/lib/motion';
import { useStats, useBuilds } from '@/hooks/useQueries';
import { useHealth } from '@/hooks/useHealth';
import { BuildCard } from '@/components/shared/BuildCard';
/* From `charts/frame`, not `charts` — the index module imports Recharts at the
   top level, and Landing lives in the entry chunk. See charts/frame.tsx. */
import { StatusBreakdown } from '@/components/charts/frame';
import { formatTokens, costOf, formatCost } from '@/lib/pricing';
import { StepTracker } from '@/components/shared/StepTracker';
import { PromptComposer } from '@/components/shared/PromptComposer';
import { promptState } from '@/lib/prompt';
import { AgentTopology } from '@/components/landing/AgentTopology';
import type { ProgressStep } from '@/hooks/useBuildProgress';
import '@/styles/landing.css';

/* Lucide defaults to a 2px stroke, which reads heavy and generic at these
   sizes. Everything on this page draws at 1.25. */
const STROKE = 1.25;

/* ─────────────────────────────────────────────
   Content
───────────────────────────────────────────── */

/**
 * Facts about the system, not claims about its record. "18 Endpoints" was
 * wrong (there are 17 public ones) and, like the proof rail below, it was a
 * hardcoded number presented as measurement. What is genuinely fixed — the
 * agent count, the typical run time — stays here; anything that varies with
 * real usage now comes from `/stats`.
 */
const HERO_STATS = [
  { value: '9',    label: 'AI agents' },
  { value: '4',    label: 'App types' },
  { value: '24/7', label: 'Available' },
];

/**
 * The nine agents, in pipeline order, named exactly as the backend names them.
 *
 * This list carried **eight** entries — Architect was missing — while the page
 * asserted a "9-agent pipeline" in four places, so anyone who counted the chips
 * caught the product contradicting itself in its own hero. The names were also
 * abbreviations of their own ("Analyzer", "Frontend") that matched nothing the
 * runner emits. Both now track `STEP_NAMES_FALLBACK` in
 * `components/shared/StepTracker.tsx`, which is the canonical set.
 */
const PIPELINE_AGENTS = [
  { name: 'Intent Analyzer',    icon: Activity     },
  { name: 'Planner',            icon: FileText     },
  { name: 'Architect',          icon: Layers       },
  { name: 'Backend Developer',  icon: Server       },
  { name: 'Frontend Generator', icon: Code         },
  { name: 'Debugger',           icon: Terminal     },
  { name: 'Reviewer',           icon: CheckCircle2 },
  { name: 'Tester',             icon: BarChart3    },
  { name: 'Documenter',         icon: Database     },
];

/**
 * `artifact` names a small piece of the real product to embed in the card —
 * see `StageArtifact`. Two of the four are read from this instance at runtime;
 * the other two carry none, because nothing true and small enough exists for
 * them and a hand-built imitation of a file tree would be exactly the drifting
 * fake this page avoids everywhere else.
 */
const STEPS: Array<{
  num: string; title: string; desc: string;
  artifact?: 'appTypes' | 'score' | 'deliverables';
}> = [
  { num: '01', title: 'Analyze & Plan',   artifact: 'appTypes',     desc: 'The Intent Analyzer extracts structured requirements from your prompt, and the Planner breaks them into ordered build steps.' },
  { num: '02', title: 'Architect & Code', desc: 'The Architect designs the folder structure, then Backend and Frontend agents generate complete, working files.' },
  { num: '03', title: 'Debug & Review',   artifact: 'score',        desc: 'The Debugger runs an autonomous fix loop on every file while the Reviewer scores code quality from 1–10.' },
  { num: '04', title: 'Test & Document',  artifact: 'deliverables', desc: 'pytest suites are generated and executed, then the Documenter writes a README with real setup instructions.' },
];

/** What every finished build hands back, named as the files are actually named. */
const DELIVERABLES = ['README.md', 'tests/', 'requirements.txt', 'project.zip'];

/**
 * Shown only until `/stats` answers, and only as the honest version of itself:
 * an em dash, not an invented number. The page used to assert "150+ Projects
 * built" and a "98% Success rate" on an instance that might have run nothing
 * at all.
 */
const PROOF_FALLBACK = [
  { value: '—',    label: 'Builds run',     icon: CheckCircle2 },
  { value: '—',    label: 'Success rate',   icon: TrendingUp   },
  { value: '—',    label: 'Avg build time', icon: Zap          },
  { value: '9',    label: 'Agents',         icon: Activity     },
];

/** 412 → "6.9m", 45 → "45s", null → "—". */
function formatBuildTime(seconds: number | null | undefined): string {
  if (seconds == null || isNaN(seconds)) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  return `${(seconds / 60).toFixed(1)}m`;
}

/**
 * Retargeted from "what is this" to "what happens when I rely on it". The first
 * answer no longer quotes a build time: the proof rail further down reads the
 * real average off this instance, and a fixed claim beside a live figure is a
 * contradiction waiting to be noticed.
 */
const FAQS = [
  { q: 'How long does a build take?',                    a: 'Most builds land in the single-digit minutes, but it depends on the app and on how much repair the Debugger has to do. The number on this page is not a marketing figure — it is the mean duration of every build this instance has actually run, and it is recalculated from the database, not written into the page.' },
  { q: 'What happens when a build fails?',               a: 'Every pipeline step is logged with its own error detail, and the build page shows exactly which agent stopped and why. Nothing is hidden behind a generic failure screen. Adjust the prompt and rebuild, or download what was produced up to that point.' },
  { q: 'What if it half-works?',                         a: 'That is a first-class outcome, not an edge case. A build that could not be fully verified finishes as "done with context": you get the code plus a handoff document naming what is unfinished and what to check. It is deliberately not reported as a clean success.' },
  { q: 'What do I actually get at the end?',             a: 'A downloadable repository: source, a generated pytest suite, a requirements file and a README with real setup steps. It is ordinary code on your disk, with no runtime dependency on this platform.' },
  { q: 'How does the review score work?',                a: 'The Reviewer agent scores code quality, architecture and adherence to the plan from 1 to 10, and the Debugger and Tester independently verify that the code imports and runs. Scores are recorded per build, so the average you see is measured across real builds rather than asserted.' },
  { q: 'What types of applications can it build?',       a: 'Web apps, CLI tools, REST APIs and data-processing scripts, in the stacks the Architect selects for the requirement. The app-type mix shown on this page is what this instance has genuinely produced.' },
  { q: 'What happens when the API quota runs out?',      a: 'Keys are rotated round-robin with automatic failover, and the pool status is visible in the hero above. If every key is exhausted, the build waits on the cooldown rather than failing silently — and deterministic repairs are attempted before any paid retry.' },
];

/* ─────────────────────────────────────────────
   1. Hero — editorial split, not a centred stack
───────────────────────────────────────────── */

function Hero() {
  const { data: stats } = useStats();

  return (
    <section className="hero">
      <div className="section__inner section__inner--wide hero__grid">
        {/* Left: the pitch */}
        <div className="hero__copy">
          <motion.div initial="hidden" animate="visible" variants={fadeUpTight}>
            <Eyebrow>
              <span className="eyebrow__dot" />
              9-agent autonomous pipeline
            </Eyebrow>
          </motion.div>

          {/* Deliberately outside the cascade below. The headline is the page's
              primary message; blurring it and holding it back 60ms meant it was
              only fully legible around 480ms, which reads as a slow page rather
              than a considered one. It rises 6px and is sharp from the first
              frame — the cascade now flows *from* it instead of after it. */}
          <motion.h1
            className="display display--lg hero__title"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: DURATION.normal, ease: EASE.out }}
          >
            {/* U+2011 non-breaking hyphen — a plain "-" lets the browser break
                the line after "full-", which read as a typo at display size.
                hyphens:none does not prevent breaking at a hard hyphen. */}
            Ship full‑stack apps from a{' '}
            <span className="display__accent">sentence</span>
          </motion.h1>

          <motion.p
            className="lede hero__lede"
            initial="hidden"
            animate="visible"
            variants={fadeUp}
            transition={{ delay: 0.06 }}
          >
            Describe the product. Nine specialised agents plan the architecture,
            write the code, debug it until it runs, test it, and hand you a
            packaged repository — while you watch each step happen.
          </motion.p>

          <motion.div
            className="hero__actions"
            initial="hidden"
            animate="visible"
            variants={fadeUp}
            transition={{ delay: 0.13 }}
          >
            <CTA to="/build" icon={<ArrowRight strokeWidth={STROKE} />}>
              Start building
            </CTA>
            <CTA to="/dashboard" variant="ghost" icon={<ArrowUpRight strokeWidth={STROKE} />}>
              View dashboard
            </CTA>
          </motion.div>

          <motion.dl
            className="hero__stats"
            initial="hidden"
            animate="visible"
            variants={fadeUp}
            transition={{ delay: 0.2 }}
          >
            {HERO_STATS.map((s) => (
              <div className="hero__stat" key={s.label}>
                <dt className="hero__stat-value">{s.value}</dt>
                <dd className="hero__stat-label">{s.label}</dd>
              </div>
            ))}
            <div className="hero__stat">
              <dt className="hero__stat-value">
                {formatBuildTime(stats?.avg_duration_seconds ?? stats?.duration_seconds?.average)}
              </dt>
              <dd className="hero__stat-label">Avg build here</dd>
            </div>
          </motion.dl>
        </div>

        {/* Right: a 2-D depiction of the thing being sold */}
        <motion.div
          className="hero__panel"
          initial={{ opacity: 0, y: 28, filter: 'blur(8px)' }}
          animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
          transition={{ duration: DURATION.glide, ease: EASE.glide, delay: 0.12 }}
        >
          <PipelinePreview />
          <HeroHealth />
        </motion.div>
      </div>
    </section>
  );
}

/**
 * The live state of the instance the visitor is looking at, under the hero
 * preview: worker capacity, key pool, provider status.
 *
 * All three come from `/health`, which the app-shell status pill already polls,
 * so this footer joins an existing react-query cache rather than adding a
 * request. `useHealth` returns `null` instead of throwing when the backend is
 * unreachable — the footer disappears and the hero is unchanged, which is the
 * correct failure mode for an ornament on a marketing page.
 *
 * Key identity is deliberately positional ("Key 03"), not the API-key suffix
 * the endpoint returns. The suffix is the tail of a live secret; the real
 * information here is how many keys there are and how many are burnt, and that
 * survives the redaction intact.
 */
function HeroHealth() {
  const { health } = useHealth();
  if (!health) return null;

  const pool = health.worker_pool;
  const llm = health.llm;

  const busy = pool.available === 0;
  const keysOut = llm.groq_keys_total > 0 && llm.groq_keys_available === 0;

  return (
    <motion.div
      className="hstat"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: DURATION.normal, ease: EASE.out, delay: 0.35 }}
    >
      <span className="hstat__cell">
        <span className={`sdot ${busy ? 'sdot--warn' : 'sdot--ok'}`} aria-hidden />
        <span className="hstat__text">
          {pool.available} of {pool.max} workers free
        </span>
      </span>

      <span className="hstat__cell">
        <span className={`sdot ${keysOut ? 'sdot--error' : 'sdot--ok'}`} aria-hidden />
        <span className="hstat__text">
          {llm.groq_keys_available}/{llm.groq_keys_total} keys in rotation
        </span>
      </span>

      <span className="hstat__cell">
        <span
          className={`sdot ${llm.status === 'healthy' ? 'sdot--ok' : 'sdot--warn'}`}
          aria-hidden
        />
        <span className="hstat__text">
          {llm.provider} {llm.status}
        </span>
      </span>
    </motion.div>
  );
}

/**
 * A static representation of a build in flight. Deliberately not animated on a
 * loop — a perpetually "running" fake build is attention-seeking motion that
 * ages badly and competes with the real dashboard.
 */
/**
 * The hero visual is the product's own `StepTracker`, not a mock-up of it.
 *
 * It used to be a hand-built imitation: a div with three macOS traffic-light
 * dots, a fake title bar, list rows styled to look like a task list, and a
 * progress footer. A fake product UI assembled out of divs is the most
 * recognisable tell in an AI-built landing page, and it carries a second cost:
 * it drifts. The real spine could be redesigned and this picture of it would
 * go quietly out of date.
 *
 * Rendering the real component means the hero cannot lie about what the app
 * looks like, and the pipeline names below are the ones the backend actually
 * emits.
 */
function PipelinePreview() {
  // Sample data — a build partway through step 5. Shaped exactly like the
  // events the runner emits, so the component renders as it does in the app.
  const SAMPLE_STEPS: ProgressStep[] = [
    { step: 1, step_name: 'intent_analyzer',    status: 'done',    timestamp: '2026-08-25T10:00:02.000Z', data: { app_type: 'web_app' } },
    { step: 2, step_name: 'planner',            status: 'done',    timestamp: '2026-08-25T10:00:14.000Z', data: { steps_count: 7 } },
    { step: 3, step_name: 'architect',          status: 'done',    timestamp: '2026-08-25T10:00:41.000Z', data: { files_count: 12 } },
    { step: 4, step_name: 'backend_developer',  status: 'done',    timestamp: '2026-08-25T10:01:58.000Z', data: { files_generated: 8 } },
    { step: 5, step_name: 'frontend_generator', status: 'running', timestamp: '2026-08-25T10:02:20.000Z' },
  ];

  return (
    <Bezel featured className="hero__panel-bezel">
      <div className="preview" aria-label="Example of a build in progress">
        <StepTracker steps={SAMPLE_STEPS} totalSteps={9} />
      </div>
    </Bezel>
  );
}

/* ─────────────────────────────────────────────
   2. Agent chain
───────────────────────────────────────────── */

function AgentChain() {
  return (
    <section className="section agents">
      <div className="section__inner section__inner--wide">
        <Reveal>
          <p className="agents__label">The pipeline</p>
        </Reveal>
        <RevealGroup className="agents__rail" step={0.045}>
          {PIPELINE_AGENTS.map((a) => {
            const Icon = a.icon;
            return (
              <RevealItem key={a.name} variants={fadeUpTight}>
                <div className="agents__chip">
                  <Icon size={15} strokeWidth={STROKE} />
                  <span>{a.name}</span>
                </div>
              </RevealItem>
            );
          })}
        </RevealGroup>
      </div>
    </section>
  );
}

/* ─────────────────────────────────────────────
   3. Prompt preview — the first step, taken here
───────────────────────────────────────────── */

/**
 * The real `PromptComposer`, on the landing page, wired to the real route.
 *
 * A picture of an input box is the single most common piece of set dressing on
 * a developer-tool landing page, and it is always slightly wrong: the wrong
 * character limit, a fake cursor, a submit button that does nothing. This is
 * the same component `/build` and the rebuild dialog use, under the same
 * 2000-character contract, so the budget meter, the readout and the validity
 * rule are the product's, not an imitation of them.
 *
 * Pressing the button carries the text to `/build` through router state, where
 * `NewBuild` seeds its composer with it. Nothing is submitted from here — the
 * build still starts on the build screen, deliberately: a marketing page that
 * silently spends the visitor's first build on an Enter keypress is not a
 * preview, it is a trapdoor.
 */
function PromptPreview() {
  const [prompt, setPrompt] = useState('');
  const navigate = useNavigate();

  const { isValid } = promptState(prompt);

  const start = () => {
    // An empty field is not an error state here; it is the default. Send the
    // visitor to /build either way and let that screen ask for the text.
    navigate('/build', { state: prompt.trim() ? { prompt: prompt.trim() } : undefined });
  };

  return (
    <section className="section section--lg" id="prompt">
      <div className="section__inner section__inner--wide prompt-try">
        <div className="prompt-try__copy">
          <Reveal><Eyebrow>One field, no configuration</Eyebrow></Reveal>
          <Reveal delay={0.05}>
            <h2 className="display display--md head__title">
              Start it <span className="display__accent">here</span>
            </h2>
          </Reveal>
          <Reveal delay={0.1}>
            <p className="lede">
              This is the product's own composer, not a picture of one — the same
              field, the same 2000-character budget, the same readout you get on
              the build screen. Whatever you type follows you there.
            </p>
          </Reveal>
          <Reveal delay={0.15}>
            <ul className="prompt-try__hints">
              <li>Name the stack if you care about it; otherwise the Architect chooses.</li>
              <li>Specific beats short — the Intent Analyzer reads what you actually wrote.</li>
              <li>Nothing is submitted from this page.</li>
            </ul>
          </Reveal>
        </div>

        <Reveal className="prompt-try__field" delay={0.08}>
          <PromptComposer
            id="landing-prompt"
            className="panel panel--accent"
            label="Your app"
            value={prompt}
            onChange={setPrompt}
            onSubmit={start}
            minHeight={150}
            placeholder={
              'A FastAPI backend for a blog platform with user auth, posts, '
              + 'comments, and a SQLite database…'
            }
            idleText="Describe the product in a sentence or two"
            actions={
              <button type="button" className="btn btn-primary" onClick={start}>
                {isValid ? 'Take this to the build screen' : 'Open the build screen'}
                <ArrowRight size={15} strokeWidth={STROKE} />
              </button>
            }
          />
        </Reveal>
      </div>
    </section>
  );
}

/**
 * One small, real thing per stage card.
 *
 * The brief this page was built from asked for embedded UI fragments here, and
 * the tempting version is four hand-drawn mock-ups — a fake file tree, a fake
 * score gauge. These are the honest form of the same idea: `appTypes` and
 * `score` are read from `/stats`, so they describe what this deployment has
 * actually produced, and both disappear on an instance that has produced
 * nothing. `deliverables` is a fixed list because it genuinely is fixed — every
 * completed build writes those four things.
 *
 * Built from the app's own classes (`.tag`, `.meter`, `.ulabel`, `.figure`)
 * rather than one-off landing markup, so a change to the design system reaches
 * them.
 */
function StageArtifact({ kind }: { kind: NonNullable<typeof STEPS[number]['artifact']> }) {
  const { data: stats } = useStats();

  if (kind === 'deliverables') {
    return (
      <ul className="stage-art stage-art--tags" aria-label="What every build hands back">
        {DELIVERABLES.map((d) => <li className="tag" key={d}>{d}</li>)}
      </ul>
    );
  }

  if (kind === 'appTypes') {
    const types = stats?.top_app_types?.slice(0, 4) ?? [];
    if (types.length === 0) return null;
    return (
      <ul className="stage-art stage-art--tags" aria-label="App types this instance has produced">
        {types.map((t) => (
          <li className="tag" key={t.type}>
            {t.type.replace(/_/g, ' ')}
            <span className="stage-art__count">{t.count}</span>
          </li>
        ))}
      </ul>
    );
  }

  // kind === 'score'
  const score = stats?.average_review_score;
  if (score == null) return null;
  return (
    <div className="stage-art stage-art__score">
      <div className="stage-art__scorehead">
        <span className="ulabel">Mean review score</span>
        <span className="figure figure--md">{score.toFixed(1)}<span className="stage-art__of">/10</span></span>
      </div>
      {/* The app's own meter, filled to the real figure — `scaleX` from a
          zero-width bar is how it animates everywhere else, and it does not
          animate here at all: this is a fact on a page, not a live reading. */}
      <div
        className="meter"
        role="img"
        aria-label={`Mean review score ${score.toFixed(1)} out of 10 across every completed build`}
      >
        <span className="meter__fill" style={{ width: `${Math.min(100, (score / 10) * 100)}%` }} />
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────
   4. How it works — asymmetric bento
───────────────────────────────────────────── */

function HowItWorks() {
  return (
    <section className="section section--lg" id="how">
      <div className="section__inner section__inner--wide">
        <div className="head">
          <Reveal delay={0.05}>
            <h2 className="display display--md head__title">
              Four stages, <span className="display__accent">no babysitting</span>
            </h2>
          </Reveal>
          <Reveal delay={0.1}>
            <p className="lede">
              Each stage hands structured output to the next. If a file fails to
              import, the loop repairs it before anything moves on.
            </p>
          </Reveal>
        </div>

        <RevealGroup className="steps" step={0.08}>
          {STEPS.map((s, i) => (
            <RevealItem
              key={s.num}
              /* The first card spans two columns — this is what breaks the
                 monotonous equal-width grid. */
              className={i === 0 ? 'steps__cell steps__cell--wide' : 'steps__cell'}
            >
              <Bezel className="steps__bezel" featured={i === 0}>
                <article className="step">
                  <span className="step__num">{s.num}</span>
                  <h3 className="step__title">{s.title}</h3>
                  <p className="step__desc">{s.desc}</p>
                  {s.artifact && <StageArtifact kind={s.artifact} />}
                </article>
              </Bezel>
            </RevealItem>
          ))}
        </RevealGroup>
      </div>
    </section>
  );
}

/**
 * The key pool as it stands right now, from `/health`.
 *
 * The obvious version of this card is an animated rotation — a highlight
 * cycling through five fake keys forever. That is a loop this codebase does not
 * allow, and it would be describing a mechanism instead of showing it working.
 * The endpoint already reports one entry per configured key with its live
 * state, so the card can simply show them.
 *
 * The endpoint also returns each key's suffix. It is not rendered: a suffix is
 * the tail of a live credential, and the argument this card makes — *this many
 * keys, this many still holding quota* — survives the redaction completely.
 * Keys are numbered by position instead.
 *
 * Renders nothing when health is unavailable, so a backend that is down leaves
 * the card as prose rather than as a broken diagram.
 */
function KeyPool() {
  const { health } = useHealth();
  const keys = health?.llm.keys;
  if (!keys || keys.length === 0) return null;

  const available = health.llm.groq_keys_available;

  return (
    <div className="keypool">
      <ul className="keypool__grid">
        {keys.map((k, i) => {
          const ok = k.status === 'available';
          return (
            <li className="keypool__key" key={k.suffix || i}>
              <span className={`sdot ${ok ? 'sdot--ok' : 'sdot--warn'}`} aria-hidden />
              <span className="keypool__name">Key {String(i + 1).padStart(2, '0')}</span>
              <span className="keypool__state">{ok ? 'ready' : k.status}</span>
            </li>
          );
        })}
      </ul>
      <p className="keypool__note">
        Live from this instance — {available} of {keys.length} holding quota.
      </p>
    </div>
  );
}

/* ─────────────────────────────────────────────
   5. Features — 1 tall + 2 stacked
───────────────────────────────────────────── */

function Features() {
  return (
    <section className="section section--lg" id="features">
      <div className="section__inner section__inner--wide">
        {/* Stacked, not split. A big left headline with a small explainer
            paragraph floating in a right-hand column is a templated section
            header; one focused message reads better and survives a narrow
            viewport without the aside becoming an orphan. */}
        <div className="head">
          <Reveal><Eyebrow>Built for real work</Eyebrow></Reveal>
          <Reveal delay={0.05}>
            <h2 className="display display--md head__title">
              Not a demo. A <span className="display__accent">pipeline</span>
            </h2>
          </Reveal>
          <Reveal delay={0.1}>
            <p className="lede">
              Quota-aware, self-repairing, and honest about what it produced.
              A degraded build still ships code and tells you what is wrong.
            </p>
          </Reveal>
        </div>

        <div className="bento">
          <Reveal className="bento__major">
            <Bezel featured className="bento__bezel">
              <article className="feature feature--major">
                <span className="feature__icon"><Activity size={18} strokeWidth={STROKE} /></span>
                <h3 className="feature__title">Nine-agent pipeline</h3>
                <p className="feature__desc">
                  An autonomous multi-agent system covering every stage of
                  delivery: requirements analysis, architecture, code
                  generation, debugging, review, testing, packaging and
                  documentation. Each agent is specialised and independently
                  verifiable.
                </p>
                <ul className="feature__list">
                  <li><CheckCircle2 size={14} strokeWidth={STROKE} /> Deterministic repair before any paid retry</li>
                  <li><CheckCircle2 size={14} strokeWidth={STROKE} /> Runtime smoke test on every generated API</li>
                  <li><CheckCircle2 size={14} strokeWidth={STROKE} /> Degraded builds still ship, with context</li>
                </ul>

                {/* The claim above is a list; this is the shape it describes.
                    Static: the branch is a fact about the pipeline, not an
                    event to animate. */}
                <AgentTopology />
              </article>
            </Bezel>
          </Reveal>

          <Reveal className="bento__minor" delay={0.06}>
            <Bezel className="bento__bezel">
              <article className="feature">
                <span className="feature__icon"><GitBranch size={18} strokeWidth={STROKE} /></span>
                <h3 className="feature__title">Multi-key rotation</h3>
                <p className="feature__desc">
                  Round-robin load balancing with automatic failover across every
                  configured key, so a single exhausted quota never ends a build.
                </p>
                <KeyPool />
              </article>
            </Bezel>
          </Reveal>

          <Reveal className="bento__minor" delay={0.12}>
            <Bezel className="bento__bezel">
              <article className="feature">
                <span className="feature__icon"><ShieldCheck size={18} strokeWidth={STROKE} /></span>
                <h3 className="feature__title">Realtime telemetry</h3>
                <p className="feature__desc">
                  Per-step progress, token spend and failure detail streamed over
                  WebSockets while the build is still running.
                </p>
              </article>
            </Bezel>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

/* ─────────────────────────────────────────────
   6. Recent builds — the real feed
───────────────────────────────────────────── */

/**
 * The last five builds this instance actually ran, rendered with the same
 * `BuildCard` the dashboard uses.
 *
 * Two deliberate choices:
 *
 *   - **The real component, not a picture of one.** Same reasoning as the hero
 *     preview above: a hand-built row of divs imitating a build card drifts the
 *     moment the real card changes, and it can quietly start lying about what
 *     the product looks like. This one cannot.
 *   - **Nothing when there is nothing.** A fresh instance renders no section at
 *     all — not a skeleton, not an empty state. A marketing page that opens
 *     with "no builds yet" argues against itself, and a spinner on a page the
 *     visitor did not ask to load data for is worse.
 *
 * Failures are not filtered out. A feed showing only successes is the kind of
 * curation a reader assumes is happening anyway, so it buys no credibility;
 * showing a cancelled or failed build beside the successful ones is the whole
 * point of putting real data here.
 */
function RecentBuilds() {
  const { data } = useBuilds();
  const { data: stats } = useStats();

  const builds = (data?.projects ?? []).slice(0, 5);
  if (builds.length === 0) return null;

  /* `ProjectList.total` is the length of the returned page, not the global
     count — `listProjects` caps at 50 — so the "view all" link takes its
     number from `/stats`, which counts the table. */
  const totalBuilds = stats?.total_builds;

  return (
    <section className="section section--lg" id="builds">
      <div className="section__inner section__inner--wide">
        <div className="head">
          <Reveal><Eyebrow>Live from this instance</Eyebrow></Reveal>
          <Reveal delay={0.05}>
            <h2 className="display display--md head__title">
              The last five <span className="display__accent">real builds</span>
            </h2>
          </Reveal>
          <Reveal delay={0.1}>
            <p className="lede">
              Read from this deployment as the page loaded — successes, failures
              and all. Every row opens the build it belongs to.
            </p>
          </Reveal>
        </div>

        {/* An app-weight island on a marketing page, and framed as one. The
            cards enter on `appItem` (≤180ms, no blur) because that is what they
            do everywhere else; the Bezel is what tells the eye that the shift in
            motion weight is deliberate. */}
        <Reveal>
          <Bezel className="feed__bezel">
            <div className="feed">
              <RevealGroup className="feed__list" step={0.05}>
                {builds.map((project) => (
                  <BuildCard key={project.build_id} project={project} />
                ))}
              </RevealGroup>

              <Link className="feed__all" to="/dashboard">
                {totalBuilds != null && totalBuilds > builds.length
                  ? `View all ${totalBuilds} builds`
                  : 'View the dashboard'}
                <ArrowUpRight size={15} strokeWidth={STROKE} />
              </Link>
            </div>
          </Bezel>
        </Reveal>
      </div>
    </section>
  );
}

/* ─────────────────────────────────────────────
   7. Analytics — the proof rail, plus the mix behind it
───────────────────────────────────────────── */

/**
 * Absorbs what used to be a standalone four-number `Proof` rail.
 *
 * The rail alone answered "how many, how often, how fast" and stopped there,
 * which is the shape of a number a marketing page invents. The outcome
 * breakdown underneath is the part that is uncomfortable to fake: it puts the
 * cancelled and failed builds in the same picture as the successful ones.
 *
 * `StatusBreakdown` is a split meter plus a legend table — pure CSS, no
 * charting library — so it costs the entry chunk nothing. The Recharts charts
 * stay on the lazily-loaded Statistics route for exactly that reason.
 */
function Analytics() {
  const { data: stats } = useStats();
  const hasBuilds = !!stats && stats.total_builds > 0;

  /**
   * Real numbers when this instance has any, honest blanks when it does not.
   * A fresh install shows dashes rather than someone else's track record.
   */
  const cells = stats && hasBuilds
    ? [
        {
          value: String(stats.total_builds),
          label: stats.total_builds === 1 ? 'Build run' : 'Builds run',
          icon: CheckCircle2,
        },
        {
          value: `${(stats.success_rate_percent ?? 0).toFixed(0)}%`,
          label: 'Success rate',
          icon: TrendingUp,
        },
        {
          value: formatBuildTime(stats.avg_duration_seconds ?? stats.duration_seconds?.average),
          label: 'Avg build time',
          icon: Zap,
        },
        { value: '9', label: 'Agents', icon: Activity },
      ]
    : PROOF_FALLBACK;

  /* Builds from before token accounting landed carry no usage at all, and a
     confident "0 tokens" beside a hundred real builds is a wrong number rather
     than a missing one. Both token figures drop out together when that holds. */
  const usage = stats?.token_usage;
  const hasTokens = !!usage && usage.total_tokens > 0;

  const figures: Array<{ label: string; value: string; note: string; icon: typeof Gauge }> = [];
  if (stats) {
    figures.push({
      label: 'Avg review score',
      value: stats.average_review_score != null
        ? `${stats.average_review_score.toFixed(1)}/10`
        : '—',
      note: 'Scored by the Reviewer agent on every completed build',
      icon: Gauge,
    });
    /* Recency is only worth a tile when there *is* any: a confident "0" beside
       three live figures reads as a dead instance, and it is the one number
       here that says nothing about the pipeline. When the week is quiet, the
       spread of app types the instance has actually produced is both true and
       still informative. */
    figures.push(
      (stats.builds_this_week ?? 0) > 0
        ? {
            label: 'Builds this week',
            value: String(stats.builds_this_week),
            note: `${stats.builds_today ?? 0} today`,
            icon: TrendingUp,
          }
        : {
            label: 'App types built',
            value: String(stats.top_app_types?.length ?? 0),
            note: stats.top_app_types?.length
              ? `Most often ${stats.top_app_types[0].type.replace(/_/g, ' ')}`
              : 'Across every build on record',
            icon: Layers,
          },
    );
    if (usage && hasTokens) {
      figures.push({
        label: 'Tokens spent',
        value: formatTokens(usage.total_tokens),
        note: usage.avg_tokens_per_build != null
          ? `${formatTokens(Math.round(usage.avg_tokens_per_build))} per build`
          : 'across every build on record',
        icon: Zap,
      });
      figures.push({
        label: 'Inference cost',
        value: formatCost(costOf(usage.total_prompt_tokens, usage.total_completion_tokens)),
        note: 'Estimated at listed rates, for everything above',
        icon: Coins,
      });
    }
  }

  return (
    <section className="section section--lg" id="proof">
      <div className="section__inner section__inner--wide">
        <Bezel className="proof__bezel">
          <RevealGroup className="proof__rail" step={0.06}>
            {cells.map((s) => {
              const Icon = s.icon;
              return (
                <RevealItem key={s.label} className="proof__cell" variants={fadeUpTight}>
                  <Icon size={16} strokeWidth={STROKE} className="proof__icon" />
                  <span className="proof__value">{s.value}</span>
                  <span className="proof__label">{s.label}</span>
                </RevealItem>
              );
            })}
          </RevealGroup>
        </Bezel>

        {/* Only once there is a mix worth showing. On a fresh instance the rail
            above already says everything that is true, in dashes. */}
        {stats && hasBuilds && (
          <div className="analytics">
            <Reveal className="analytics__chart">
              <StatusBreakdown byStatus={stats.by_status ?? {}} />
            </Reveal>

            {/* App-weight, like the feed above: these are dashboard figures and
                they enter the way dashboard figures do. */}
            <motion.div
              className="analytics__figures"
              variants={appStagger(0.05)}
              initial="hidden"
              whileInView="visible"
              viewport={viewportOnce}
            >
              {figures.map((f) => {
                const Icon = f.icon;
                return (
                  <RevealItem
                    key={f.label}
                    className="panel panel--pad afig"
                    variants={appItem}
                  >
                    <span className="afig__head">
                      <Icon size={14} strokeWidth={STROKE} />
                      <span className="ulabel">{f.label}</span>
                    </span>
                    <span className="figure figure--lg afig__value">{f.value}</span>
                    <span className="afig__note">{f.note}</span>
                  </RevealItem>
                );
              })}
            </motion.div>
          </div>
        )}
      </div>
    </section>
  );
}

/* ─────────────────────────────────────────────
   8. FAQ
───────────────────────────────────────────── */

function Faq() {
  const [open, setOpen] = useState<number | null>(0);

  return (
    <section className="section section--lg" id="faq">
      {/* Editorial split: the heading holds the left rail while the questions
          scroll past it, instead of stranding half the viewport empty. */}
      <div className="section__inner section__inner--wide faq">
        <div className="faq__aside">
          <Reveal delay={0.05}>
            <h2 className="display display--sm faq__title">Common questions</h2>
          </Reveal>
          <Reveal delay={0.1}>
            <p className="faq__note">
              Still unsure? Start a build. The pipeline explains itself as it runs.
            </p>
          </Reveal>
        </div>

        <ul className="faq__list">
          {FAQS.map((f, i) => {
            const isOpen = open === i;
            return (
              <Reveal as="li" key={f.q} delay={i * 0.04} className="faq__item">
                <button
                  className={`faq__q ${isOpen ? 'is-open' : ''}`}
                  onClick={() => setOpen(isOpen ? null : i)}
                  aria-expanded={isOpen}
                >
                  <span>{f.q}</span>
                  <span className="faq__sign" aria-hidden>
                    <Plus size={16} strokeWidth={STROKE} />
                  </span>
                </button>

                {/* Opening an FAQ is a rare interaction, so a height transition
                    is affordable here in a way it would not be in the dashboard. */}
                <AnimatePresence initial={false}>
                  {isOpen && (
                    <motion.div
                      key="a"
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: DURATION.normal, ease: EASE.glide }}
                      style={{ overflow: 'hidden' }}
                    >
                      <p className="faq__a">{f.a}</p>
                    </motion.div>
                  )}
                </AnimatePresence>
              </Reveal>
            );
          })}
        </ul>
      </div>
    </section>
  );
}

/* ─────────────────────────────────────────────
   9. Closing CTA
───────────────────────────────────────────── */

function ClosingCTA() {
  return (
    <section className="section section--lg">
      <div className="section__inner">
        <Reveal>
          <Bezel featured className="closing__bezel">
            <div className="closing">
              <Eyebrow>Ready when you are</Eyebrow>
              <h2 className="display display--md closing__title">
                Describe it. <span className="display__accent">Ship it.</span>
              </h2>
              <p className="lede closing__lede">
                No boilerplate, no scaffolding, no setup. One prompt to a
                packaged, tested repository.
              </p>
              {/* What lands on disk, named as the files are named. The CTA used
                  to end on the word "repository" and leave the reader to guess
                  what was in it. */}
              <ul className="closing__delivery">
                {DELIVERABLES.map((d) => <li className="tag" key={d}>{d}</li>)}
              </ul>
              <div className="closing__actions">
                <CTA to="/build" icon={<ArrowRight strokeWidth={STROKE} />}>
                  Start your first build
                </CTA>
              </div>
            </div>
          </Bezel>
        </Reveal>
      </div>
    </section>
  );
}

/* ─────────────────────────────────────────────
   Page
───────────────────────────────────────────── */

export default function Landing() {
  return (
    <div className="landing">
      <AmbientMesh />
      <div className="landing__content">
        <Hero />
        <AgentChain />
        <PromptPreview />
        <HowItWorks />
        <Features />
        <RecentBuilds />
        <Analytics />
        <Faq />
        <ClosingCTA />
      </div>
    </div>
  );
}
