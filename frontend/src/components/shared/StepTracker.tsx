import { Check, X, Loader, Minus, AlertTriangle } from 'lucide-react';
import { AnimatePresence, motion } from 'framer-motion';
import type { ProgressStep } from '../../hooks/useBuildProgress';
import { popIn, disclose, appItem, appStagger, EASE, DURATION } from '../../lib/motion';
import './StepTracker.css';

/**
 * StepTracker — the pipeline spine.
 *
 * This is the component the user stares at for three to eight minutes, so it
 * is built to be read at a glance and to be boring while nothing is happening.
 *
 * Design rules applied here:
 *   - The rail reads as one continuous line, but each segment carries its own
 *     step's status colour (see the note above the list).
 *   - Exactly one row is ever emphasised: the running one. Pending rows are
 *     dimmed, completed rows recede to secondary. That is the whole hierarchy.
 *   - Step numbers are mono and tabular so the column does not shift when the
 *     list crosses from single to double digits.
 *
 * ── Motion ────────────────────────────────────────────────────────────────
 * A step completing is the only thing that happens on this screen, and it can
 * be several minutes apart from the last one. If it is not marked, the user
 * looks away and misses it; if it is over-marked, nine of them in a row is a
 * fireworks display. So the marker — and only the marker — springs, once, on
 * the frame its status actually changes:
 *
 *   `<AnimatePresence mode="wait">` keyed on `status` swaps the old glyph out
 *   and the new one in. Keying on status rather than on the step means a
 *   re-render from an unrelated WebSocket event does not replay it.
 *
 * Everything else is held still on purpose:
 *   - The rows enter staggered on first mount, then never animate again.
 *   - The meter interpolates its value; it does not pulse.
 *   - The spinner still loops, because it is tied to real in-flight work and
 *     stops when the work does. It is the app's one permitted loop.
 */

/**
 * Fallback labels, used ONLY until the server has sent a `step_name` for that
 * slot. Once it has, the emitted name always wins — several slots run two
 * agents and only the server knows which one is currently in the slot.
 *
 * Slot 9 previously read "Packager", an agent that does not exist anywhere in
 * the pipeline. The real one is `documenter`.
 */
const STEP_NAMES_FALLBACK: Record<number, string> = {
  1: 'Intent Analyzer',
  2: 'Planner',
  3: 'Architect',
  4: 'Backend Developer',
  5: 'Frontend Generator',
  6: 'Debugger',
  7: 'Reviewer',
  8: 'Tester',
  9: 'Documenter',
};

/** "backend_developer" → "Backend Developer" */
function formatStepName(raw: string): string {
  return raw.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

interface StepTrackerProps {
  steps:        ProgressStep[];
  totalSteps?:  number;
  /** The runner's slot -1 failure event, if the pipeline raised. */
  terminalStep?: ProgressStep | null;
}

/** The glyph and tone for one status, with no motion of its own. */
function markerFor(status: string) {
  if (status === 'done')              return { tone: 'done',    glyph: <Check size={11} strokeWidth={3} /> };
  if (status === 'failed')            return { tone: 'failed',  glyph: <X size={11} strokeWidth={3} /> };
  if (status === 'done_with_context') return { tone: 'warn',    glyph: <AlertTriangle size={10} strokeWidth={2.75} /> };
  if (status === 'running')           return { tone: 'running', glyph: <Loader size={11} strokeWidth={2.5} className="spin-icon" /> };
  return { tone: 'pending', glyph: <Minus size={10} strokeWidth={3} /> };
}

/**
 * `mode="wait"` so the outgoing glyph is gone before the incoming one arrives.
 * Overlapping them would cross-fade a dash into a tick inside a 16px circle,
 * which at that size is just a smudge. The marker is `position: relative` in
 * CSS and the animation is scale+opacity only, so the row's layout never moves
 * while it plays.
 */
function StepMarker({ status }: { status: string }) {
  const { tone, glyph } = markerFor(status);
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.span
        key={status}
        className={`smark smark--${tone}`}
        variants={popIn}
        initial="hidden"
        animate="visible"
        exit="exit"
      >
        {glyph}
      </motion.span>
    </AnimatePresence>
  );
}

/**
 * What the backend actually sends per step.
 *
 * The old version rendered `data.message`, a field the pipeline never emits —
 * so this line was dead markup on every row. `_build_step_data` emits a small,
 * per-agent shape instead; these are the fields worth a line of text.
 */
function stepDetail(data: Record<string, unknown> | undefined): string | null {
  if (!data) return null;
  const n = (k: string) => (typeof data[k] === 'number' ? data[k] as number : undefined);
  const s = (k: string) => (typeof data[k] === 'string' ? data[k] as string : undefined);

  // A failure explains itself first.
  const error = s('error');
  if (error) return error;

  const parts: string[] = [];

  const files = n('files_generated');
  if (files !== undefined) parts.push(`${files} file${files === 1 ? '' : 's'} generated`);

  const fileCount = n('files_count');
  if (fileCount !== undefined) parts.push(`${fileCount} files planned`);

  const stepsCount = n('steps_count');
  if (stepsCount !== undefined) parts.push(`${stepsCount} tasks`);

  const appType = s('app_type');
  if (appType) parts.push(appType);

  const checked = n('ts_files_checked');
  if (checked !== undefined) {
    parts.push(`${checked} checked, ${n('ts_files_fixed') ?? 0} fixed`);
  }

  const avgScore = n('avg_score');
  if (avgScore !== undefined) parts.push(`avg score ${avgScore}`);

  const reviewed = n('files_reviewed');
  if (reviewed !== undefined) parts.push(`${reviewed} reviewed`);

  const passed = n('passed');
  const total  = n('total');
  if (passed !== undefined && total !== undefined) parts.push(`${passed}/${total} passed`);

  const elapsed = n('elapsed_seconds');
  if (elapsed !== undefined) parts.push(`${Math.round(elapsed)}s`);

  const reason = s('reason');
  if (reason) parts.push(reason);

  return parts.length ? parts.join(' · ') : null;
}

export function StepTracker({ steps, totalSteps = 9, terminalStep = null }: StepTrackerProps) {
  /**
   * Slots 5, 8 and 9 each run two agents, so more than one event can land on
   * one slot. Keep the most recent per slot rather than whichever arrived last
   * in array order, and render the name that slot actually emitted.
   */
  const bySlot = new Map<number, ProgressStep>();
  for (const s of steps) {
    const held = bySlot.get(s.step);
    if (!held || s.timestamp >= held.timestamp) bySlot.set(s.step, s);
  }

  const completedCount = Array.from(bySlot.values())
    .filter(s => s.status === 'done' || s.status === 'done_with_context').length;
  const progressPct = Math.round((completedCount / totalSteps) * 100);

  return (
    <div className="steptrack">

      <header className="steptrack__head">
        <span className="ulabel">Pipeline</span>
        <span className="steptrack__count figure figure--sm">
          {completedCount}
          <span className="figure__unit">of {totalSteps}</span>
        </span>
      </header>

      <div
        className="meter steptrack__meter"
        role="progressbar"
        aria-valuenow={progressPct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Pipeline progress"
      >
        {/*
          Driven by motion rather than the shared `.meter__fill` CSS transition
          so the bar animates up from zero on mount as well as between values.
          A CSS transition has no starting state to leave on first paint, so
          reloading a build that was already at step 6 used to snap the bar to
          60% with no movement at all — the one moment the progress is worth
          showing off.

          `scaleX` on a `transform-origin: left` element, not `width`: width is
          a layout property and animating it re-runs layout on the parent for
          every frame of the build.
        */}
        <motion.div
          className="meter__fill steptrack__fill"
          initial={{ scaleX: 0 }}
          animate={{ scaleX: progressPct / 100 }}
          transition={{ duration: DURATION.slow, ease: EASE.out }}
        />
      </div>

      {/* The rail is drawn per row as a full-height ::before at the marker's
          x-position, so it reads as one continuous line but each segment can
          colour itself from its own step's status. A single absolutely
          positioned rail cannot do that, and a rail filled by percentage of
          the list height would drift out of register with the markers as soon
          as one row wrapped to two lines. */}
      <motion.ol
        className="steptrack__list"
        variants={appStagger(0.035)}
        initial="hidden"
        animate="visible"
      >
        {Array.from({ length: totalSteps }, (_, i) => i + 1).map(stepNum => {
          const step   = bySlot.get(stepNum);
          const status = step?.status ?? 'pending';

          const rawName = step?.step_name ?? '';
          const name    = rawName
            ? formatStepName(rawName)
            : (STEP_NAMES_FALLBACK[stepNum] ?? `Step ${stepNum}`);
          const detail = stepDetail(step?.data);

          return (
            /* `variants` only — the enter is inherited from the <ol>, so the
               rows cascade once on mount and are then static. Re-rendering the
               list on every WebSocket frame does not replay it. */
            <motion.li key={stepNum} className={`srow srow--${status}`} variants={appItem}>
              <span className="srow__n figure">{String(stepNum).padStart(2, '0')}</span>

              <StepMarker status={status} />

              <div className="srow__body">
                <div className="srow__top">
                  <span className="srow__name">{name}</span>
                  {status === 'running'           && <span className="srow__tag">running</span>}
                  {status === 'failed'            && <span className="srow__tag srow__tag--failed">failed</span>}
                  {status === 'done_with_context' && <span className="srow__tag srow__tag--warn">partial</span>}
                  {step?.timestamp && (
                    <time className="srow__time">
                      {new Date(step.timestamp).toLocaleTimeString([], {
                        hour: '2-digit', minute: '2-digit', second: '2-digit',
                      })}
                    </time>
                  )}
                </div>
                {/* The detail arrives after the row already exists — an agent
                    reports "14 files generated" seconds into its step. It
                    discloses rather than appearing, so the rows below are
                    pushed down visibly instead of jumping. */}
                <AnimatePresence initial={false}>
                  {detail && (
                    <motion.p
                      key={detail}
                      className="srow__msg"
                      variants={disclose}
                      initial="hidden"
                      animate="visible"
                      exit="exit"
                    >
                      {detail}
                    </motion.p>
                  )}
                </AnimatePresence>
              </div>
            </motion.li>
          );
        })}

        {/* The runner emits its pipeline-level failure on slot -1, outside
            1..N. The list used to render only the numbered slots, so this
            event — the one that says *why* the build died — was dropped and
            the page showed nine pending rows with no explanation. */}
        {/* The failure row is the one element here that appears mid-session
            rather than on mount, so it gets its own enter — otherwise the row
            that explains why the build died materialises with no transition
            at all, and reads as if it had been there the whole time. */}
        <AnimatePresence>
        {terminalStep && (
          <motion.li
            className="srow srow--failed srow--terminal"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0, transition: { duration: DURATION.normal, ease: EASE.out } }}
            exit={{ opacity: 0, transition: { duration: DURATION.instant, ease: EASE.in } }}
          >
            <span className="srow__n figure" aria-hidden>!!</span>
            <StepMarker status="failed" />
            <div className="srow__body">
              <div className="srow__top">
                <span className="srow__name">Pipeline stopped</span>
                <span className="srow__tag srow__tag--failed">failed</span>
                {terminalStep.timestamp && (
                  <time className="srow__time">
                    {new Date(terminalStep.timestamp).toLocaleTimeString([], {
                      hour: '2-digit', minute: '2-digit', second: '2-digit',
                    })}
                  </time>
                )}
              </div>
              {stepDetail(terminalStep.data) && (
                <p className="srow__msg srow__msg--error">{stepDetail(terminalStep.data)}</p>
              )}
            </div>
          </motion.li>
        )}
        </AnimatePresence>
      </motion.ol>
    </div>
  );
}
