import { useState, useRef } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Send, X, Globe, Terminal, Code2, Database,
  AlertCircle, Sparkles,
} from 'lucide-react';
import { api } from '../api/client';
import { PromptComposer } from '../components/shared/PromptComposer';
import { promptState } from '../lib/prompt';
import { appItem, appStagger, disclose, pressableSubtle } from '../lib/motion';
import './NewBuild.css';

/**
 * NewBuild — the prompt entry screen.
 *
 * This is the highest-intent surface in the product: everything else is
 * inspection, this is the one place the user creates something. The layout is
 * asymmetric on purpose — the composer takes the dominant column and the
 * pipeline rail sits beside it as reference, rather than the old single
 * centred stack where the textarea, the hint and the examples all competed at
 * the same width.
 *
 * Motion is Emil-weighted (restraint): no reveals, no stagger, no scroll
 * animation. The only transitions are focus and hover state on the composer,
 * all under 150ms.
 */

const EXAMPLES = [
  {
    icon: Globe,
    label: 'Web App',
    text: 'A React task manager app with drag-and-drop boards, due dates, and local storage persistence.',
  },
  {
    icon: Terminal,
    label: 'CLI Tool',
    text: 'A Python CLI tool that renames files in bulk using regex patterns with a dry-run preview mode.',
  },
  {
    icon: Code2,
    label: 'REST API',
    text: 'A FastAPI URL shortener with SQLite storage, analytics dashboard, and custom slug support.',
  },
  {
    icon: Database,
    label: 'Data Script',
    text: 'A Python script that fetches stock prices from Yahoo Finance and generates a CSV report with charts.',
  },
] as const;

/**
 * The nine slots, in pipeline order, named as the backend actually names them
 * — the rail is a preview of the exact list the user watches on the next
 * screen, not decoration, so a name that does not exist in the pipeline makes
 * it a lie. Slot 9 read "Packager"; the agent is `documenter`.
 *
 * Slots 5 and 8 each run a second agent (frontend_debugger, remediation) that
 * the roles below fold in rather than listing separately, since the spine
 * shows one row per slot.
 */
const PIPELINE = [
  { n: 1, name: 'Intent Analyzer',    role: 'Reads the prompt, decides app type and complexity' },
  { n: 2, name: 'Planner',            role: 'Breaks the build into ordered tasks' },
  { n: 3, name: 'Architect',          role: 'Chooses stack, lays out the file tree' },
  { n: 4, name: 'Backend Developer',  role: 'Writes server, models and data layer' },
  { n: 5, name: 'Frontend Generator', role: 'Writes UI, then type-checks what it wrote' },
  { n: 6, name: 'Debugger',           role: 'Runs the code, fixes what breaks' },
  { n: 7, name: 'Reviewer',           role: 'Scores quality, flags weak spots' },
  { n: 8, name: 'Tester',             role: 'Executes the generated suite, repairs failures' },
  { n: 9, name: 'Documenter',         role: 'Writes the README and packages the ZIP' },
] as const;

export default function NewBuild() {
  /**
   * Landing's prompt preview hands its text over through router state, so a
   * visitor who starts typing on the marketing page arrives here with what
   * they wrote already in the composer rather than facing an empty box.
   *
   * Read once as `useState`'s initial value, not synced: after the first
   * render this field belongs to the user, and re-applying the navigation
   * state would fight their edits on every re-render.
   */
  const { state } = useLocation() as { state?: { prompt?: string } };
  const [prompt, setPrompt] = useState(state?.prompt ?? '');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const navigate = useNavigate();

  // The length contract and the readout state machine are shared with the
  // rebuild modal — see lib/prompt.ts.
  const { isValid } = promptState(prompt);
  const canSubmit = isValid && !isSubmitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const res = await api.createProject(prompt.trim());
      navigate(`/build/${res.build_id}`);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to start build. Is the backend running?';
      setError(message);
      setIsSubmitting(false);
    }
  };

  const applyExample = (text: string) => {
    setPrompt(text);
    textareaRef.current?.focus();
  };

  return (
    <div className="new-build page-wrapper">

      <header className="page-head nb-head">
        <div className="page-head__text">
          <span className="page-head__kicker">
            <Sparkles size={11} strokeWidth={2} />
            Nine-agent pipeline
          </span>
          <h1 className="page-head__title">
            Describe what you want <em>built</em>
          </h1>
          <p className="page-head__sub">
            Plain English is enough. The pipeline architects, writes, debugs,
            reviews and tests the app on its own, then hands back a ZIP.
          </p>
        </div>
      </header>

      <div className="nb-layout">

        {/* ── Composer ─────────────────────────────────────────────────────
             The accent surface. It is the only panel on this screen that
             carries the brand tint, so the eye lands here first.          */}
        <section className="nb-compose">
          <PromptComposer
            ref={textareaRef}
            id="build-prompt-input"
            className="panel panel--accent"
            label="Your app"
            value={prompt}
            onChange={setPrompt}
            onSubmit={handleSubmit}
            disabled={isSubmitting}
            placeholder={
              'A FastAPI backend for a blog platform with user auth, posts, '
              + 'comments, and a SQLite database…'
            }
            actions={
              <>
                {/* Appears the moment the field stops being empty. Without a
                    transition a button materialises next to the primary action
                    at the exact instant the user is typing toward it, which is
                    how mis-clicks happen. */}
                <AnimatePresence initial={false}>
                  {prompt && !isSubmitting && (
                    <motion.button
                      key="clear"
                      className="btn btn-ghost btn-icon"
                      onClick={() => { setPrompt(''); textareaRef.current?.focus(); }}
                      aria-label="Clear prompt"
                      title="Clear"
                      initial={{ opacity: 0, scale: 0.85 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, scale: 0.85 }}
                      transition={{ duration: 0.12 }}
                      whileTap={{ scale: 0.94 }}
                    >
                      <X size={15} />
                    </motion.button>
                  )}
                </AnimatePresence>
                <button
                  className="btn btn-primary"
                  onClick={handleSubmit}
                  disabled={!canSubmit}
                  id="start-build-btn"
                >
                  {isSubmitting
                    ? <><div className="spinner" /> Launching agents…</>
                    : <><Send size={15} /> Build app</>
                  }
                </button>
              </>
            }
          />

          {/* The submit failed. It discloses rather than fading so the chips
              below are pushed down visibly — an error that appears by simply
              existing, in a spot the user was not looking at, gets missed. */}
          <AnimatePresence initial={false}>
            {error && (
              /*
                The animated element is an unpadded wrapper, not the panel
                itself. `height: 0` on a padded, border-box element still
                renders its own padding and border — the panel would collapse
                to a 34px sliver rather than to nothing. An outer box with no
                box of its own has nothing left to render at zero.
              */
              <motion.div
                key={error}
                className="nb-error-slot"
                variants={disclose}
                initial="hidden"
                animate="visible"
                exit="exit"
              >
                <div className="nb-error panel" role="alert">
                  <AlertCircle size={16} className="nb-error__icon" />
                  <div>
                    <p className="nb-error__title">Could not start the build</p>
                    <p className="nb-error__body">{error}</p>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Examples as chips, not as a 2×2 card grid. They are a shortcut
              into the field above, so they belong beside it at label scale —
              four equal cards below the composer made them look like the
              primary content of the page. */}
          <div className="nb-examples">
            <span className="ulabel">Start from</span>
            <div className="nb-examples__row">
              {EXAMPLES.map(({ icon: Icon, label, text }) => (
                <motion.button
                  key={label}
                  type="button"
                  className="chip"
                  onClick={() => applyExample(text)}
                  title={text}
                  whileHover={{ y: -1 }}
                  {...pressableSubtle}
                >
                  <Icon size={12} strokeWidth={2} />
                  {label}
                </motion.button>
              ))}
            </div>
          </div>
        </section>

        {/* ── Pipeline rail ────────────────────────────────────────────────
             Reference, not action. Sets the expectation for the next screen
             and answers "what is it actually going to do".                */}
        <aside className="nb-rail panel">
          <div className="nb-rail__head">
            <span className="ulabel">What runs next</span>
            <span className="figure figure--sm nb-rail__count">
              9<span className="figure__unit">agents</span>
            </span>
          </div>

          {/* The rail is the page's explanation of what the nine agents are.
              It cascades once on mount, top to bottom, which is the order they
              will actually run in — the stagger is doing a small amount of
              real explanatory work rather than just being a cascade. */}
          <motion.ol
            className="nb-rail__list"
            variants={appStagger(0.035, 0.08)}
            initial="hidden"
            animate="visible"
          >
            {PIPELINE.map(({ n, name, role }) => (
              <motion.li key={n} className="nb-step" variants={appItem}>
                <span className="nb-step__n figure">{String(n).padStart(2, '0')}</span>
                <span className="nb-step__body">
                  <span className="nb-step__name">{name}</span>
                  <span className="nb-step__role">{role}</span>
                </span>
              </motion.li>
            ))}
          </motion.ol>

          <p className="nb-rail__note">
            Typical run is 3–8 minutes. Short pauses are normal — Groq keys
            rotate automatically when one hits its rate limit.
          </p>
        </aside>
      </div>
    </div>
  );
}
