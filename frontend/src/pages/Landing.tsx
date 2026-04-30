import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, type Variants } from 'framer-motion';
import { SplineScene } from '@/components/ui/splite';
import { ShaderAnimation } from '@/components/ui/shader-animation';
import { Spotlight } from '@/components/ui/spotlight';
import { Card } from '@/components/ui/card';
import {
  ArrowRight,
  Play,
  Zap,
  CheckCircle2,
  Clock,
  TrendingUp,
  FileText,
  ChevronRight,
  Activity,
  Sparkles,
  Code,
  Terminal,
  Database,
  Server,
  BarChart3,
  ChevronDown,
} from 'lucide-react';

/* ─────────────────────────────────────────────
   Shared animation variants
───────────────────────────────────────────── */
const fadeUp: Variants = {
  hidden: { opacity: 0, y: 32 },
  visible: (i = 0) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.75, delay: 0.15 + i * 0.12, ease: [0.22, 1, 0.36, 1] },
  }),
};

const fadeIn: Variants = {
  hidden: { opacity: 0 },
  visible: (i = 0) => ({
    opacity: 1,
    transition: { duration: 0.6, delay: 0.1 + i * 0.1 },
  }),
};

/* ─────────────────────────────────────────────
   Shared section wrapper — handles centering +
   consistent vertical rhythm across all sections
───────────────────────────────────────────── */
function Section({
  children,
  className = '',
  bg = '',
  id,
}: {
  children: React.ReactNode;
  className?: string;
  bg?: string;
  id?: string;
}) {
  return (
    <section
      id={id}
      className={`landing-section ${className}`}
      style={bg ? { background: bg } : undefined}
    >
      <div className="section-inner">{children}</div>
    </section>
  );
}

function SectionHeading({
  eyebrow,
  title,
  subtitle,
  custom = 0,
}: {
  eyebrow?: string;
  title: React.ReactNode;
  subtitle?: string;
  custom?: number;
}) {
  return (
    <div className="section-heading">
      {eyebrow && (
        <motion.span
          className="eyebrow"
          variants={fadeIn}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true }}
          custom={custom}
        >
          {eyebrow}
        </motion.span>
      )}
      <motion.h2
        className="section-title"
        variants={fadeUp}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true }}
        custom={custom + 1}
      >
        {title}
      </motion.h2>
      {subtitle && (
        <motion.p
          className="section-subtitle"
          variants={fadeUp}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true }}
          custom={custom + 2}
        >
          {subtitle}
        </motion.p>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────
   1. HERO
───────────────────────────────────────────── */
function HeroSection() {
  const navigate = useNavigate();

  return (
    <section className="hero-section">
      {/* Shader background */}
      <div className="hero-shader">
        <ShaderAnimation />
      </div>

      {/* Gradient overlays */}
      <div className="hero-overlay-1" />
      <motion.div
        className="hero-blob hero-blob--left"
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 0.35, scale: 1 }}
        transition={{ duration: 2.5, ease: 'easeOut' }}
      />
      <motion.div
        className="hero-blob hero-blob--right"
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 0.22, scale: 1 }}
        transition={{ duration: 2.5, delay: 0.3, ease: 'easeOut' }}
      />
      <Spotlight className="hero-spotlight" fill="#FFD700" />

      {/* Content */}
      <div className="hero-content">
        <motion.div className="hero-badge" variants={fadeUp} initial="hidden" animate="visible" custom={0}>
          <Sparkles size={14} />
          <span>9-Agent AI Pipeline</span>
        </motion.div>

        <motion.h1 className="hero-title" variants={fadeUp} initial="hidden" animate="visible" custom={1}>
          <span className="hero-title--line1">Build Full-Stack Apps</span>
          <br />
          <span className="hero-title--line2">From Text Prompts</span>
        </motion.h1>

        <motion.p className="hero-subtitle" variants={fadeUp} initial="hidden" animate="visible" custom={2}>
          Autonomous 9-agent pipeline that generates, reviews, debugs, and packages
          complete applications in under 8 minutes.
        </motion.p>

        <motion.div className="hero-cta" variants={fadeUp} initial="hidden" animate="visible" custom={3}>
          <button className="btn-hero-primary" onClick={() => navigate('/build')}>
            Start Building
            <ArrowRight size={18} className="btn-arrow" />
          </button>
          <button className="btn-hero-secondary" onClick={() => navigate('/dashboard')}>
            <Play size={16} />
            View Dashboard
          </button>
        </motion.div>

        <motion.div className="hero-stats" variants={fadeUp} initial="hidden" animate="visible" custom={4}>
          {[
            { value: '9', label: 'AI Agents' },
            { value: '18', label: 'Endpoints' },
            { value: '<8min', label: 'Avg Build' },
            { value: '24/7', label: 'Available' },
          ].map(s => (
            <div key={s.label} className="hero-stat">
              <span className="hero-stat-value">{s.value}</span>
              <span className="hero-stat-label">{s.label}</span>
            </div>
          ))}
        </motion.div>

        {/* Scroll cue */}
        <motion.div
          className="hero-scroll-cue"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 2, duration: 1 }}
        >
          <ChevronDown size={20} />
        </motion.div>
      </div>
    </section>
  );
}

/* ─────────────────────────────────────────────
   2. INTERACTIVE SHOWCASE (3-D Spline)
───────────────────────────────────────────── */
function ShowcaseSection() {
  return (
    <Section bg="linear-gradient(180deg,#2C1810 0%,#3E2723 100%)">
      <Card className="showcase-card">
        <Spotlight className="showcase-spotlight" fill="#FFD700" />
        <div className="showcase-inner">
          {/* Left */}
          <motion.div
            className="showcase-text"
            variants={fadeUp}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            custom={0}
          >
            <h2 className="showcase-heading">
              Interactive 3D
              <br />
              <span className="showcase-heading--accent">AI-Powered Dev</span>
            </h2>
            <p className="showcase-body">
              Experience the future of application development with our autonomous AI agents.
              Watch as your ideas transform into production-ready code in real-time with
              immersive 3D visualisation and cutting-edge technology.
            </p>
            <button className="btn-showcase" onClick={() => {}}>
              Explore Pipeline
            </button>
          </motion.div>

          {/* Right — 3D */}
          <motion.div
            className="showcase-3d"
            initial={{ opacity: 0, scale: 0.92 }}
            whileInView={{ opacity: 1, scale: 1 }}
            viewport={{ once: true }}
            transition={{ duration: 0.8, delay: 0.2 }}
          >
            <SplineScene
              scene="https://prod.spline.design/kZDDjO5HuC9GJUM2/scene.splinecode"
              className="spline-scene"
            />
          </motion.div>
        </div>
      </Card>
    </Section>
  );
}

/* ─────────────────────────────────────────────
   3. PIPELINE VISUALISER  ← MORE SPACE HERE
───────────────────────────────────────────── */
const PIPELINE_AGENTS = [
  { name: 'Analyzer',  icon: Activity   },
  { name: 'Planner',   icon: FileText   },
  { name: 'Frontend',  icon: Code       },
  { name: 'Backend',   icon: Server     },
  { name: 'Reviewer',  icon: CheckCircle2 },
  { name: 'Debugger',  icon: Terminal   },
  { name: 'Tester',    icon: BarChart3  },
  { name: 'Packager',  icon: Database   },
];

function PipelineSection() {
  return (
    <Section
      id="pipeline"
      bg="linear-gradient(180deg,#3E2723 0%,#2C1810 100%)"
      className="pipeline-section"
    >
      <SectionHeading
        eyebrow="How it works"
        title={<>9‑Agent Pipeline</>}
        subtitle="Each agent specialises in a specific task, working in sequence to deliver
          production-ready, tested, and documented applications."
      />

      {/* Agent row */}
      <div className="pipeline-agents">
        {PIPELINE_AGENTS.map((agent, idx) => (
          <React.Fragment key={agent.name}>
            <motion.div
              className="pipeline-agent"
              variants={fadeUp}
              initial="hidden"
              whileInView="visible"
              viewport={{ once: true }}
              custom={idx * 0.5}
            >
              <div className="pipeline-agent-icon">
                <agent.icon size={26} />
              </div>
              <span className="pipeline-agent-name">{agent.name}</span>
              <span className="pipeline-agent-num">0{idx + 1}</span>
            </motion.div>

            {idx < PIPELINE_AGENTS.length - 1 && (
              <ChevronRight className="pipeline-connector" size={20} />
            )}
          </React.Fragment>
        ))}
      </div>

      {/* Step descriptions */}
      <div className="pipeline-steps">
        {[
          { num: '01', title: 'Analyze & Plan',    desc: 'The Intent Analyzer extracts structured requirements from your prompt and the Planner breaks it into ordered build steps.' },
          { num: '02', title: 'Architect & Code',  desc: 'The Architect designs the folder structure, then Backend and Frontend agents generate complete, working code files.' },
          { num: '03', title: 'Debug & Review',    desc: 'The Debugger runs an autonomous fix loop on every file, while the Reviewer scores code quality from 1–10.' },
          { num: '04', title: 'Test & Document',   desc: 'pytest tests are generated and executed. The Documenter writes a complete README with setup instructions.' },
        ].map((step, idx) => (
          <motion.div
            key={step.num}
            className="pipeline-step-card"
            variants={fadeUp}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            custom={idx}
          >
            <span className="pipeline-step-num">{step.num}</span>
            <h3 className="pipeline-step-title">{step.title}</h3>
            <p className="pipeline-step-desc">{step.desc}</p>
          </motion.div>
        ))}
      </div>
    </Section>
  );
}

/* ─────────────────────────────────────────────
   4. FEATURES  ← MORE SPACE, CENTERED
───────────────────────────────────────────── */
const FEATURES = [
  {
    icon: Activity,
    title: '9-Agent Pipeline',
    desc: 'Autonomous multi-agent system that handles every aspect of application development — from requirements analysis all the way through to packaging and documentation.',
    gradient: 'from-[#FF8C42] to-[#D2691E]',
  },
  {
    icon: Zap,
    title: 'Groq Multi-Key Rotation',
    desc: 'Intelligent API key management ensures uninterrupted service with automatic failover and round-robin load balancing across all your Groq keys.',
    gradient: 'from-[#FFD700] to-[#FF8C42]',
  },
  {
    icon: TrendingUp,
    title: 'Realtime Analytics',
    desc: 'Live monitoring of build progress, resource usage, and performance metrics delivered through WebSocket connections with per-step granularity.',
    gradient: 'from-[#FFDEAD] to-[#FFD700]',
  },
];

function FeaturesSection() {
  return (
    <Section
      id="features"
      bg="linear-gradient(180deg,#2C1810 0%,#3E2723 100%)"
      className="features-section"
    >
      <SectionHeading
        eyebrow="Core features"
        title="Built to ship, not to impress"
        subtitle="Every feature exists to reduce the gap between your idea and a working,
          tested, downloadable application."
      />

      <div className="features-grid">
        {FEATURES.map((f, idx) => (
          <motion.div
            key={f.title}
            className="feature-card"
            variants={fadeUp}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            custom={idx}
          >
            <div className="feature-icon-wrap">
              <f.icon size={28} className="feature-icon" />
            </div>
            <h3 className="feature-title">{f.title}</h3>
            <p className="feature-desc">{f.desc}</p>
          </motion.div>
        ))}
      </div>
    </Section>
  );
}

/* ─────────────────────────────────────────────
   5. SOCIAL PROOF / STATS  ← MORE SPACE
───────────────────────────────────────────── */
const PROOF_STATS = [
  { value: '150+',  label: 'Projects Built',   icon: CheckCircle2 },
  { value: '98%',   label: 'Success Rate',      icon: TrendingUp   },
  { value: '7.5m',  label: 'Avg Build Time',    icon: Clock        },
  { value: '24/7',  label: 'Uptime',            icon: Activity     },
];

function ProofSection() {
  return (
    <Section
      id="proof"
      bg="linear-gradient(180deg,#3E2723 0%,#2C1810 100%)"
      className="proof-section"
    >
      <SectionHeading
        eyebrow="Trusted results"
        title="Numbers that speak"
        subtitle="Consistent performance across every build, every time."
      />

      <div className="proof-grid">
        {PROOF_STATS.map((s, idx) => (
          <motion.div
            key={s.label}
            className="proof-card"
            variants={fadeUp}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            custom={idx}
          >
            <s.icon size={32} className="proof-icon" />
            <span className="proof-value">{s.value}</span>
            <span className="proof-label">{s.label}</span>
          </motion.div>
        ))}
      </div>
    </Section>
  );
}

/* ─────────────────────────────────────────────
   6. FAQ  ← MORE SPACE
───────────────────────────────────────────── */
const FAQS = [
  { q: 'How long does it take to build an application?', a: 'The 9-agent pipeline typically completes a full-stack application in under 8 minutes, including code generation, review, debugging, testing, and packaging.' },
  { q: 'What types of applications can I build?', a: 'Web apps, CLI tools, REST APIs, and data processing scripts. The system supports multiple frameworks and languages based on your requirements.' },
  { q: 'How does the AI review process work?', a: 'The Reviewer agent analyses code quality, architecture, and best practices, providing scores from 1–10. The Debugger and Tester agents then validate functionality.' },
  { q: 'Can I customise the generated code?', a: 'Yes. Download the complete source code, modify it as needed, and trigger a rebuild with updated requirements through the dashboard.' },
  { q: 'What happens if a build fails?', a: 'Detailed logs are provided for each pipeline step. Review the error, adjust your prompt, and retry with a single click.' },
];

function FAQSection() {
  const [open, setOpen] = useState<number | null>(null);

  return (
    <Section
      id="faq"
      bg="linear-gradient(180deg,#2C1810 0%,#3E2723 100%)"
      className="faq-section"
    >
      <SectionHeading
        eyebrow="FAQ"
        title="Common questions"
        subtitle="Everything you need to know before your first build."
      />

      <div className="faq-list">
        {FAQS.map((faq, idx) => (
          <motion.div
            key={idx}
            className={`faq-item${open === idx ? ' faq-item--open' : ''}`}
            variants={fadeUp}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            custom={idx * 0.4}
          >
            <button
              className="faq-question"
              onClick={() => setOpen(open === idx ? null : idx)}
              aria-expanded={open === idx}
            >
              <span>{faq.q}</span>
              <ChevronRight
                size={18}
                className="faq-chevron"
                style={{ transform: open === idx ? 'rotate(90deg)' : 'rotate(0deg)' }}
              />
            </button>
            {open === idx && (
              <motion.p
                className="faq-answer"
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25 }}
              >
                {faq.a}
              </motion.p>
            )}
          </motion.div>
        ))}
      </div>
    </Section>
  );
}

/* ─────────────────────────────────────────────
   7. CTA FOOTER
───────────────────────────────────────────── */
function CTASection() {
  const navigate = useNavigate();

  return (
    <Section
      id="cta"
      bg="linear-gradient(180deg,#3E2723 0%,#1a0f0a 100%)"
      className="cta-section"
    >
      <SectionHeading
        eyebrow="Get started"
        title="Ready to build your app?"
        subtitle="Join developers using our AI-powered platform to bring ideas to life — no boilerplate, no setup, just describe and ship."
      />

      <motion.div
        className="cta-buttons"
        variants={fadeUp}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true }}
        custom={3}
      >
        <button className="btn-hero-primary" onClick={() => navigate('/build')}>
          Start Building Free
          <ArrowRight size={18} className="btn-arrow" />
        </button>
        <button className="btn-hero-secondary" onClick={() => navigate('/dashboard')}>
          Open Dashboard
        </button>
      </motion.div>
    </Section>
  );
}

/* ─────────────────────────────────────────────
   ROOT LANDING PAGE
───────────────────────────────────────────── */
export default function Landing() {
  return (
    <div className="landing-root">
      {/* Scoped styles injected as a <style> tag so they don't leak */}
      <style>{LANDING_CSS}</style>

      <HeroSection />
      <ShowcaseSection />
      <PipelineSection />
      <FeaturesSection />
      <ProofSection />
      <FAQSection />
      <CTASection />
    </div>
  );
}

/* ─────────────────────────────────────────────
   ALL LANDING CSS — scoped under .landing-root
   so it cannot conflict with app shell styles.
───────────────────────────────────────────── */
const LANDING_CSS = `
/* ── Root ───────────────────────────────── */
.landing-root {
  width: 100%;
  min-height: 100vh;
  background: #2C1810;
  color: #FFE4B5;
  font-family: 'Inter', sans-serif;
  overflow-x: hidden;
}

/* ── Section rhythm ─────────────────────── */
/*  Every content section gets the same wrapper.
    Vertical padding is generous (120px top/bottom)
    so sections breathe independently. */
.landing-section {
  width: 100%;
  padding: 120px 24px;
}

.section-inner {
  max-width: 1100px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;   /* ← centred horizontally */
  gap: 0;
}

/* ── Section heading block ──────────────── */
.section-heading {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;    /* ← all heading text centred */
  gap: 18px;
  margin-bottom: 80px;   /* ← generous space below heading before content */
  max-width: 680px;
}

.eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #FFD700;
  background: rgba(255,215,0,0.08);
  border: 1px solid rgba(255,215,0,0.2);
  padding: 6px 16px;
  border-radius: 9999px;
}

.section-title {
  font-size: clamp(2rem, 4vw, 3rem);
  font-weight: 800;
  line-height: 1.15;
  letter-spacing: -0.03em;
  background: linear-gradient(135deg, #FFE4B5, #FFD700);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  text-align: center;
  margin: 0;
}

.section-subtitle {
  font-size: 1.0625rem;
  line-height: 1.7;
  color: rgba(255,228,181,0.75);
  text-align: center;
  max-width: 560px;
  margin: 0;
}

/* ── HERO ───────────────────────────────── */
.hero-section {
  position: relative;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: linear-gradient(135deg,#2C1810,#3E2723,#5D4037);
}

.hero-shader {
  position: absolute;
  inset: 0;
  opacity: 0.28;
}

.hero-overlay-1 {
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg,rgba(210,105,30,0.25),transparent,rgba(255,140,66,0.15));
  pointer-events: none;
}

.hero-blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  pointer-events: none;
}
.hero-blob--left  { top:10%; left:-5%;  width:55vw; height:55vw; background:#FF8C42; }
.hero-blob--right { bottom:10%; right:-5%; width:45vw; height:45vw; background:#D2691E; }

.hero-spotlight { top: -40%; left: 40%; }

.hero-content {
  position: relative;
  z-index: 10;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 28px;
  padding: 0 24px;
  max-width: 900px;
}

.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #FFD700;
  background: rgba(255,215,0,0.1);
  border: 1px solid rgba(255,215,0,0.25);
  padding: 8px 20px;
  border-radius: 9999px;
  backdrop-filter: blur(8px);
}

.hero-title {
  font-size: clamp(2.75rem, 7vw, 5.5rem);
  font-weight: 900;
  line-height: 1.05;
  letter-spacing: -0.04em;
  margin: 0;
}

.hero-title--line1 {
  display: block;
  background: linear-gradient(180deg,#FFE4B5,#FFD700);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.hero-title--line2 {
  display: block;
  background: linear-gradient(90deg,#FF8C42,#FFD700,#FFE4B5);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.hero-subtitle {
  font-size: clamp(1rem, 2vw, 1.2rem);
  line-height: 1.7;
  color: rgba(255,228,181,0.85);
  max-width: 600px;
  margin: 0;
}

.hero-cta {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  justify-content: center;
}

.btn-hero-primary {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 16px 32px;
  font-size: 1rem;
  font-weight: 700;
  color: #2C1810;
  background: linear-gradient(135deg,#FF8C42,#FFD700);
  border: none;
  border-radius: 9999px;
  cursor: pointer;
  transition: box-shadow 0.25s, transform 0.15s;
  box-shadow: 0 4px 24px rgba(255,140,66,0.35);
}

.btn-hero-primary:hover {
  box-shadow: 0 6px 32px rgba(255,215,0,0.45);
  transform: translateY(-1px);
}

.btn-hero-primary:active { transform: scale(0.97); }

.btn-arrow { transition: transform 0.2s; }
.btn-hero-primary:hover .btn-arrow { transform: translateX(3px); }

.btn-hero-secondary {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 16px 32px;
  font-size: 1rem;
  font-weight: 600;
  color: #FFE4B5;
  background: rgba(255,228,181,0.08);
  border: 2px solid rgba(255,140,66,0.4);
  border-radius: 9999px;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s;
  backdrop-filter: blur(8px);
}

.btn-hero-secondary:hover {
  background: rgba(255,140,66,0.15);
  border-color: rgba(255,215,0,0.6);
}

.hero-stats {
  display: flex;
  gap: 48px;
  flex-wrap: wrap;
  justify-content: center;
  margin-top: 12px;
}

.hero-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.hero-stat-value {
  font-size: 2.25rem;
  font-weight: 800;
  color: #FFD700;
  letter-spacing: -0.04em;
  line-height: 1;
}

.hero-stat-label {
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(255,228,181,0.6);
}

.hero-scroll-cue {
  color: rgba(255,228,181,0.4);
  animation: bounce 2s ease-in-out infinite;
  margin-top: 8px;
}

@keyframes bounce {
  0%,100% { transform: translateY(0);   }
  50%      { transform: translateY(6px); }
}

/* ── SHOWCASE ───────────────────────────── */
.showcase-card {
  width: 100%;
  height: 580px;
  background: rgba(26,15,10,0.85) !important;
  border: 1px solid rgba(255,140,66,0.25) !important;
  border-radius: 24px !important;
  overflow: hidden;
  position: relative;
}

.showcase-spotlight { top: -30%; left: 50%; }

.showcase-inner {
  display: flex;
  height: 100%;
}

.showcase-text {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 24px;
  padding: 64px 56px;
  position: relative;
  z-index: 10;
}

.showcase-heading {
  font-size: clamp(2rem, 3.5vw, 2.75rem);
  font-weight: 800;
  line-height: 1.15;
  letter-spacing: -0.03em;
  color: #FFE4B5;
  background: linear-gradient(180deg,#FFE4B5,#FF8C42);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin: 0;
}

.showcase-heading--accent { color: #FFD700; }

.showcase-body {
  font-size: 1.0625rem;
  line-height: 1.75;
  color: rgba(255,228,181,0.8);
  max-width: 400px;
  margin: 0;
}

.btn-showcase {
  align-self: flex-start;
  padding: 14px 28px;
  font-size: 0.9375rem;
  font-weight: 700;
  color: #2C1810;
  background: linear-gradient(135deg,#FF8C42,#FFD700);
  border: none;
  border-radius: 9999px;
  cursor: pointer;
  transition: box-shadow 0.2s;
}

.btn-showcase:hover { box-shadow: 0 4px 20px rgba(255,215,0,0.4); }

.showcase-3d {
  flex: 1;
  position: relative;
}

.spline-scene { width: 100%; height: 100%; }

/* ── PIPELINE ───────────────────────────── */
.pipeline-section .section-inner { gap: 0; }

/* Agent row */
.pipeline-agents {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 12px;
  width: 100%;
  margin-bottom: 80px;   /* ← space before step cards */
}

.pipeline-agent {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  position: relative;
}

.pipeline-agent-icon {
  width: 80px;
  height: 80px;
  border-radius: 20px;
  background: linear-gradient(135deg,rgba(255,140,66,0.15),rgba(210,105,30,0.1));
  border: 2px solid rgba(255,140,66,0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #FFD700;
  transition: background 0.2s, border-color 0.2s, transform 0.2s, box-shadow 0.2s;
}

.pipeline-agent-icon:hover {
  background: rgba(255,140,66,0.25);
  border-color: #FFD700;
  transform: translateY(-3px);
  box-shadow: 0 8px 24px rgba(255,140,66,0.3);
}

.pipeline-agent-name {
  font-size: 0.75rem;
  font-weight: 700;
  color: #FFE4B5;
  text-align: center;
  letter-spacing: 0.04em;
}

.pipeline-agent-num {
  font-size: 10px;
  font-weight: 700;
  color: rgba(255,215,0,0.5);
  font-family: 'JetBrains Mono', monospace;
}

.pipeline-connector {
  color: rgba(255,140,66,0.5);
  flex-shrink: 0;
  margin-top: -20px; /* align with icon centres */
}

/* Step cards */
.pipeline-steps {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 24px;
  width: 100%;
}

@media (max-width: 900px) {
  .pipeline-steps { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 560px) {
  .pipeline-steps { grid-template-columns: 1fr; }
}

.pipeline-step-card {
  background: linear-gradient(135deg,rgba(26,15,10,0.8),rgba(44,24,16,0.6));
  border: 1px solid rgba(255,140,66,0.2);
  border-radius: 20px;
  padding: 36px 28px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  text-align: left;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.pipeline-step-card:hover {
  border-color: rgba(255,215,0,0.4);
  box-shadow: 0 4px 24px rgba(255,140,66,0.15);
}

.pipeline-step-num {
  font-size: 2rem;
  font-weight: 900;
  color: rgba(255,215,0,0.25);
  font-family: 'JetBrains Mono', monospace;
  letter-spacing: -0.04em;
  line-height: 1;
}

.pipeline-step-title {
  font-size: 1.0625rem;
  font-weight: 700;
  color: #FFE4B5;
  margin: 0;
}

.pipeline-step-desc {
  font-size: 0.875rem;
  line-height: 1.7;
  color: rgba(255,228,181,0.65);
  margin: 0;
}

/* ── FEATURES ───────────────────────────── */
.features-section .section-inner { gap: 0; }

.features-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 28px;
  width: 100%;
}

@media (max-width: 860px) {
  .features-grid { grid-template-columns: 1fr; }
}

.feature-card {
  background: linear-gradient(135deg,rgba(26,15,10,0.85),rgba(44,24,16,0.65));
  border: 2px solid rgba(255,140,66,0.2);
  border-radius: 28px;
  padding: 52px 40px;          /* ← generous internal padding */
  display: flex;
  flex-direction: column;
  align-items: center;         /* ← icon + text centred */
  text-align: center;          /* ← text centred */
  gap: 22px;
  transition: border-color 0.25s, box-shadow 0.25s, transform 0.2s;
  position: relative;
  overflow: hidden;
}

.feature-card::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg,rgba(255,140,66,0.07),rgba(255,215,0,0.04));
  opacity: 0;
  transition: opacity 0.25s;
}

.feature-card:hover {
  border-color: #FFD700;
  box-shadow: 0 8px 40px rgba(255,140,66,0.2);
  transform: translateY(-4px);
}

.feature-card:hover::before { opacity: 1; }

.feature-icon-wrap {
  width: 72px;
  height: 72px;
  border-radius: 20px;
  background: linear-gradient(135deg,rgba(255,140,66,0.15),rgba(255,215,0,0.08));
  border: 1px solid rgba(255,140,66,0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.25s, box-shadow 0.25s;
}

.feature-card:hover .feature-icon-wrap {
  transform: scale(1.08);
  box-shadow: 0 0 24px rgba(255,215,0,0.3);
}

.feature-icon { color: #FFD700; }

.feature-title {
  font-size: 1.25rem;
  font-weight: 800;
  color: #FFE4B5;
  margin: 0;
  letter-spacing: -0.02em;
}

.feature-desc {
  font-size: 0.9375rem;
  line-height: 1.75;
  color: rgba(255,228,181,0.7);
  margin: 0;
}

/* ── PROOF ──────────────────────────────── */
.proof-section .section-inner { gap: 0; }

.proof-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 24px;
  width: 100%;
}

@media (max-width: 860px) {
  .proof-grid { grid-template-columns: repeat(2, 1fr); }
}

.proof-card {
  display: flex;
  flex-direction: column;
  align-items: center;   /* ← centred */
  text-align: center;
  gap: 14px;
  padding: 52px 32px;
  background: linear-gradient(135deg,rgba(255,140,66,0.08),rgba(210,105,30,0.04));
  border: 2px solid rgba(255,140,66,0.25);
  border-radius: 28px;
  transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;
}

.proof-card:hover {
  border-color: #FFD700;
  box-shadow: 0 8px 32px rgba(255,140,66,0.2);
  transform: translateY(-3px);
}

.proof-icon { color: #FFD700; }

.proof-value {
  font-size: 2.5rem;
  font-weight: 900;
  color: #FFE4B5;
  letter-spacing: -0.05em;
  line-height: 1;
}

.proof-label {
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: rgba(255,228,181,0.55);
}

/* ── FAQ ────────────────────────────────── */
.faq-section .section-inner { gap: 0; }

.faq-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  width: 100%;
  max-width: 760px;
}

.faq-item {
  border-radius: 18px;
  background: linear-gradient(135deg,rgba(26,15,10,0.85),rgba(44,24,16,0.65));
  border: 2px solid rgba(255,140,66,0.2);
  overflow: hidden;
  transition: border-color 0.2s;
}

.faq-item--open,
.faq-item:hover { border-color: rgba(255,215,0,0.45); }

.faq-question {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 24px 28px;
  background: none;
  border: none;
  color: #FFE4B5;
  font-size: 1rem;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s;
  line-height: 1.5;
}

.faq-question:hover { background: rgba(255,140,66,0.06); }

.faq-chevron {
  flex-shrink: 0;
  color: #FFD700;
  transition: transform 0.25s;
}

.faq-answer {
  padding: 0 28px 28px;
  font-size: 0.9375rem;
  line-height: 1.75;
  color: rgba(255,228,181,0.72);
  margin: 0;
}

/* ── CTA ────────────────────────────────── */
.cta-section .section-inner {
  align-items: center;
  text-align: center;
}

.cta-buttons {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  justify-content: center;
  margin-top: 16px;
}
`;
