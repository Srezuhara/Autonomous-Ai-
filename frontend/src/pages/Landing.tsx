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
import '@/styles/landing.css';

/* Lucide defaults to a 2px stroke, which reads heavy and generic at these
   sizes. Everything on this page draws at 1.25. */
const STROKE = 1.25;

/* ─────────────────────────────────────────────
   Content
───────────────────────────────────────────── */

const HERO_STATS = [
  { value: '9',     label: 'AI agents'   },
  { value: '18',    label: 'Endpoints'   },
  { value: '<8min', label: 'Avg build'   },
  { value: '24/7',  label: 'Available'   },
];

const PIPELINE_AGENTS = [
  { name: 'Analyzer',  icon: Activity     },
  { name: 'Planner',   icon: FileText     },
  { name: 'Frontend',  icon: Code         },
  { name: 'Backend',   icon: Server       },
  { name: 'Reviewer',  icon: CheckCircle2 },
  { name: 'Debugger',  icon: Terminal     },
  { name: 'Tester',    icon: BarChart3    },
  { name: 'Packager',  icon: Database     },
];

const STEPS = [
  { num: '01', title: 'Analyze & Plan',   desc: 'The Intent Analyzer extracts structured requirements from your prompt, and the Planner breaks them into ordered build steps.' },
  { num: '02', title: 'Architect & Code', desc: 'The Architect designs the folder structure, then Backend and Frontend agents generate complete, working files.' },
  { num: '03', title: 'Debug & Review',   desc: 'The Debugger runs an autonomous fix loop on every file while the Reviewer scores code quality from 1–10.' },
  { num: '04', title: 'Test & Document',  desc: 'pytest suites are generated and executed, then the Documenter writes a README with real setup instructions.' },
];

const PROOF_STATS = [
  { value: '150+', label: 'Projects built',  icon: CheckCircle2 },
  { value: '98%',  label: 'Success rate',    icon: TrendingUp   },
  { value: '7.5m', label: 'Avg build time',  icon: Zap          },
  { value: '24/7', label: 'Uptime',          icon: Activity     },
];

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

          <motion.h1
            className="display display--lg hero__title"
            initial="hidden"
            animate="visible"
            variants={fadeUp}
            transition={{ delay: 0.06 }}
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
            transition={{ delay: 0.13 }}
          >
            Describe the product. Nine specialised agents plan the architecture,
            write the code, debug it until it runs, test it, and hand you a
            packaged repository — in under eight minutes.
          </motion.p>

          <motion.div
            className="hero__actions"
            initial="hidden"
            animate="visible"
            variants={fadeUp}
            transition={{ delay: 0.2 }}
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
            transition={{ delay: 0.27 }}
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
function PipelinePreview() {
  const rows = [
    { step: 'intent_analyzer',   state: 'done',    ms: '1.7s'  },
    { step: 'planner',           state: 'done',    ms: '2.4s'  },
    { step: 'architect',         state: 'done',    ms: '6.1s'  },
    { step: 'backend_developer', state: 'running', ms: '—'     },
    { step: 'frontend_generator', state: 'queued', ms: '—'     },
    { step: 'debugger',          state: 'queued',  ms: '—'     },
  ];

  return (
    <Bezel featured className="hero__panel-bezel">
      <div className="preview">
        <header className="preview__bar">
          <span className="preview__dots" aria-hidden>
            <i /><i /><i />
          </span>
          <span className="preview__title">build · todo_app</span>
          <span className="preview__badge">running</span>
        </header>

        <ul className="preview__rows">
          {rows.map((r) => (
            <li key={r.step} className={`preview__row preview__row--${r.state}`}>
              <span className="preview__state" aria-hidden />
              <span className="preview__step">{r.step}</span>
              <span className="preview__ms">{r.ms}</span>
            </li>
          ))}
        </ul>

        <footer className="preview__foot">
          <div className="preview__meter" aria-hidden>
            <span style={{ width: '58%' }} />
          </div>
          <span className="preview__foot-label">4 / 9 steps · 58%</span>
        </footer>
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
          <Reveal><Eyebrow>How it works</Eyebrow></Reveal>
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
        <div className="head head--split">
          <div>
            <Reveal><Eyebrow>Built for real work</Eyebrow></Reveal>
            <Reveal delay={0.05}>
              <h2 className="display display--md head__title">
                Not a demo. A <span className="display__accent">pipeline</span>
              </h2>
            </Reveal>
          </div>
          <Reveal delay={0.1}>
            <p className="lede head__aside">
              Quota-aware, self-repairing and honest about what it produced —
              a degraded build still ships code and tells you what is wrong.
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
                  delivery — requirements analysis, architecture, code
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
  return (
    <section className="section proof">
      <div className="section__inner section__inner--wide">
        <Bezel className="proof__bezel">
          <RevealGroup className="proof__rail" step={0.06}>
            {PROOF_STATS.map((s) => {
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
          <Reveal><Eyebrow>FAQ</Eyebrow></Reveal>
          <Reveal delay={0.05}>
            <h2 className="display display--sm faq__title">Common questions</h2>
          </Reveal>
          <Reveal delay={0.1}>
            <p className="faq__note">
              Still unsure? Start a build — the pipeline explains itself as it runs.
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
