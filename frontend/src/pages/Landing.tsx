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
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowRight, ArrowUpRight, Activity, FileText, Code, Server,
  CheckCircle2, Terminal, BarChart3, Database, Zap, TrendingUp,
  Plus, ShieldCheck, GitBranch,
} from 'lucide-react';
import {
  AmbientMesh, Bezel, Eyebrow, CTA, Reveal, RevealGroup, RevealItem,
} from '@/components/ui/primitives';
import { fadeUp, fadeUpTight, EASE, DURATION } from '@/lib/motion';
import { useStats } from '@/hooks/useQueries';
import { StepTracker } from '@/components/shared/StepTracker';
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
  { value: '9',     label: 'AI agents'  },
  { value: '4',     label: 'App types'  },
  { value: '<8min', label: 'Avg build'  },
  { value: '24/7',  label: 'Available'  },
];

const PIPELINE_AGENTS = [
  { name: 'Analyzer',  icon: Activity     },
  { name: 'Planner',   icon: FileText     },
  { name: 'Frontend',  icon: Code         },
  { name: 'Backend',   icon: Server       },
  { name: 'Reviewer',  icon: CheckCircle2 },
  { name: 'Debugger',  icon: Terminal     },
  { name: 'Tester',    icon: BarChart3    },
  { name: 'Documenter', icon: Database    },
];

const STEPS = [
  { num: '01', title: 'Analyze & Plan',   desc: 'The Intent Analyzer extracts structured requirements from your prompt, and the Planner breaks them into ordered build steps.' },
  { num: '02', title: 'Architect & Code', desc: 'The Architect designs the folder structure, then Backend and Frontend agents generate complete, working files.' },
  { num: '03', title: 'Debug & Review',   desc: 'The Debugger runs an autonomous fix loop on every file while the Reviewer scores code quality from 1–10.' },
  { num: '04', title: 'Test & Document',  desc: 'pytest suites are generated and executed, then the Documenter writes a README with real setup instructions.' },
];

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

const FAQS = [
  { q: 'How long does it take to build an application?', a: 'The 9-agent pipeline typically completes a full-stack application in under 8 minutes, including code generation, review, debugging, testing and packaging.' },
  { q: 'What types of applications can I build?',        a: 'Web apps, CLI tools, REST APIs and data-processing scripts. The system supports multiple frameworks and languages based on your requirements.' },
  { q: 'How does the AI review process work?',           a: 'The Reviewer agent analyses code quality, architecture and best practices, scoring from 1–10. The Debugger and Tester agents then validate that it actually runs.' },
  { q: 'Can I customise the generated code?',            a: 'Yes. Download the complete source, modify it as needed, and trigger a rebuild with updated requirements from the dashboard.' },
  { q: 'What happens if a build fails?',                 a: 'Detailed logs are captured for every pipeline step. Review the error, adjust your prompt, and retry with a single click.' },
];

/* ─────────────────────────────────────────────
   1. Hero — editorial split, not a centred stack
───────────────────────────────────────────── */

function Hero() {
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
            packaged repository, in under eight minutes.
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
        </motion.div>
      </div>
    </section>
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
   3. How it works — asymmetric bento
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
                </article>
              </Bezel>
            </RevealItem>
          ))}
        </RevealGroup>
      </div>
    </section>
  );
}

/* ─────────────────────────────────────────────
   4. Features — 1 tall + 2 stacked
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
   5. Proof rail
───────────────────────────────────────────── */

function Proof() {
  const { data: stats } = useStats();

  /**
   * Real numbers when this instance has any, honest blanks when it does not.
   * A fresh install shows dashes rather than someone else's track record.
   */
  const cells = stats && stats.total_builds > 0
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

  return (
    <section className="section proof">
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
      </div>
    </section>
  );
}

/* ─────────────────────────────────────────────
   6. FAQ
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
   7. Closing CTA
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
        <HowItWorks />
        <Features />
        <Proof />
        <Faq />
        <ClosingCTA />
      </div>
    </div>
  );
}
