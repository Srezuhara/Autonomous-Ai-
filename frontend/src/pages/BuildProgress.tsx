import { useParams, Link } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import {
  Wifi, CheckCircle2, AlertTriangle, ArrowLeft,
  ExternalLink, Loader, X, RadioTower,
} from 'lucide-react';
import { useBuildProgress } from '../hooks/useBuildProgress';
import { useProjectDetail } from '../hooks/useQueries';
import { useHealth } from '../hooks/useHealth';
import { api, isDownloadable } from '../api/client';
import { StepTracker } from '../components/shared/StepTracker';
import { StatusBadge } from '../components/shared/StatusBadge';
import { appItem, appStagger, popIn, EASE, DURATION } from '../lib/motion';
import './BuildProgress.css';

/**
 * BuildProgress — the live build screen.
 *
 * The most Emil-weighted surface in the app. It updates continuously over a
 * WebSocket for minutes at a time, so almost everything that could move has
 * been made to hold still:
 *
 *   - The connection pill no longer pulses on a 1.6s / 2s infinite loop. Two
 *     separate looping animations sat at the top of a screen whose entire job
 *     is to report change; the loops made real state changes harder to notice,
 *     not easier.
 *   - Nothing animates per log line or per step event.
 *   - The single remaining animation is the spinner inside the active step's
 *     marker, which stops the moment that step completes.
 *
 * The layout is a spine plus a status column, and the status column's contents
 * change with build state rather than stacking every possible card.
 *
 * ── Motion ────────────────────────────────────────────────────────────────
 * Everything that moves here is a transition between two *build states*, never
 * decoration, because this screen is open for minutes and anything ambient
 * becomes unbearable inside the first one:
 *
 *   - The connection pill swaps its whole contents when the socket state
 *     changes — connecting → live → closed. It is the only indicator that the
 *     stream is healthy, so the change has to be seen.
 *   - The title and subtitle recompose when the build finishes. That sentence
 *     going from "Step 4 of 9 in progress" to "All 9 agents finished" is the
 *     payoff of the whole screen and used to happen between two frames.
 *   - The outcome notes (failed / partial / cancelled / degraded stream) enter
 *     on arrival and are keyed so only one is ever mid-flight.
 *   - The aside cascades once on mount and is then still.
 */

// ── WS status pill ─────────────────────────────────────────────────────────────
function WsStatusPill({ status }: { status: string }) {
  type PillConfig = { label: string; tone: string; icon: React.ReactNode };

  const MAP: Record<string, PillConfig> = {
    connecting: {
      label: 'Connecting',
      tone:  'idle',
      icon:  <Loader size={12} className="spin-icon" />,
    },
    live: {
      label: 'Live',
      tone:  'running',
      icon:  <Wifi size={12} />,
    },
    done: {
      label: 'Stream closed',
      tone:  'ok',
      icon:  <CheckCircle2 size={12} />,
    },
    error: {
      label: 'Polling',
      tone:  'warn',
      icon:  <RadioTower size={12} />,
    },
  };

  const cfg: PillConfig = MAP[status] ?? MAP.connecting;

  /*
    Keyed on `status`, so the pill re-enters only when the socket actually
    changes state. `mode="wait"` prevents two pills of different widths
    existing at once, which would shove the header's right edge sideways
    mid-transition.
  */
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.span
        key={status}
        className={`wspill wspill--${cfg.tone}`}
        variants={popIn}
        initial="hidden"
        animate="visible"
        exit="exit"
      >
        {cfg.icon}
        {cfg.label}
      </motion.span>
    </AnimatePresence>
  );
}

/** 95 → "1m 35s", 8 → "8s". Compact enough for a summary row. */
function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rest = s % 60;
  return rest ? `${m}m ${rest}s` : `${m}m`;
}

// ── Page ───────────────────────────────────────────────────────────────────────
export default function BuildProgress() {
  const { id } = useParams<{ id: string }>();

  const { steps, terminalStep, wsStatus, buildDone, buildStatus, meta } = useBuildProgress(id);
  const { data: project } = useProjectDetail(buildDone ? id : undefined);
  const { health } = useHealth();

  // The server knows how many steps the pipeline has. Hardcoding 9 meant the
  // page would silently misreport the moment the pipeline changed length.
  const totalSteps = meta.totalSteps ?? 9;

  const isFinished   = buildDone;
  const actualStatus = project?.status ?? buildStatus;
  const hasFailed    = isFinished && actualStatus === 'failed';
  // A cancelled build used to fall through to the success branch and read
  // "Build complete — your files are ready to download", which was false in
  // every particular.
  const isCancelled  = isFinished && actualStatus === 'cancelled';
  // Phase 21: a done_with_context build produced downloadable code, so it gets
  // the "View Result" path — not the failure path.
  const isPartial    = isFinished && actualStatus === 'done_with_context';
  const hasSucceeded = isFinished && isDownloadable(actualStatus);

  const stepsComplete = steps.filter(
    s => s.status === 'done' || s.status === 'done_with_context'
  ).length;
  const runningStep = steps.find(s => s.status === 'running');

  const title = !isFinished
    ? 'Building your app'
    : hasFailed    ? 'Build failed'
    : isCancelled  ? 'Build cancelled'
    : isPartial    ? 'Finished with notes'
    : 'Build complete';

  const subtitle = !isFinished
    ? (meta.queuePosition != null
        ? `Queued — position ${meta.queuePosition}. The build starts when a worker frees up.`
        : runningStep
        ? `Step ${runningStep.step} of ${totalSteps} in progress.`
        : 'Waiting for the first agent to report in.')
    : hasFailed
    ? 'The pipeline stopped before it could package anything.'
    : isCancelled
    ? `Stopped on request after ${stepsComplete} of ${totalSteps} steps. Nothing was packaged.`
    : isPartial
    ? 'Code was produced, but not every verification step ran.'
    : `All ${totalSteps} agents finished. Your files are ready to download.`;

  /**
   * The failure text lives in `completion_reason`. `project.error` was read in
   * three places across the app and the column does not exist on the projects
   * table at all, so the fallback string was the only thing that ever showed.
   * The runner's slot -1 payload is the more specific source when we have it.
   */
  const failureText =
    (terminalStep?.data?.error as string | undefined)
    ?? project?.completion_reason
    ?? meta.completionReason
    ?? 'Check the step log above for the failing agent.';

  // ── Cancel handler ─────────────────────────────────────────────────────────
  const handleCancel = async () => {
    if (!id) return;
    if (!confirm('Cancel this build? The pipeline will stop at its current step.')) return;
    try {
      await api.cancelJob(id);
      // Build will transition to "cancelled" — WS/polling will pick it up
    } catch (err) {
      console.error('Cancel failed:', err);
      alert('Failed to cancel build. It may have already finished.');
    }
  };

  return (
    <div className="build-progress page-wrapper">

      <Link to="/dashboard" className="back-link bp-back">
        <ArrowLeft size={14} /> Dashboard
      </Link>

      <header className="page-head bp-head">
        <div className="page-head__text">
          <span className="page-head__kicker">
            <span className="bp-id">{id}</span>
          </span>
          {/* The heading and the line under it are the build's verdict. They
              are keyed on their own text so the crossfade fires when the
              wording changes — and, crucially, not on every one of the dozens
              of step events that re-render this component with identical
              copy. */}
          <AnimatePresence mode="wait" initial={false}>
            <motion.h1
              key={title}
              className="page-head__title"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: DURATION.normal, ease: EASE.out }}
            >
              {title}
            </motion.h1>
          </AnimatePresence>
          <AnimatePresence mode="wait" initial={false}>
            <motion.p
              key={subtitle}
              className="page-head__sub"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: DURATION.fast, ease: EASE.out }}
            >
              {subtitle}
            </motion.p>
          </AnimatePresence>
        </div>
        <div className="page-head__aside">
          <WsStatusPill status={wsStatus} />
        </div>
      </header>

      <div className="bp-layout">

        {/* ── Spine ──────────────────────────────────────────────────────── */}
        <motion.section
          className="panel panel--pad-lg bp-spine"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: DURATION.normal, ease: EASE.out }}
        >
          <StepTracker steps={steps} totalSteps={totalSteps} terminalStep={terminalStep} />
        </motion.section>

        {/* ── Status column ──────────────────────────────────────────────── */}
        <motion.aside
          className="bp-aside"
          variants={appStagger(0.045)}
          initial="hidden"
          animate="visible"
        >

          <motion.div className="panel panel--pad bp-summary" variants={appItem}>
            <div className="bp-summary__row">
              <span className="ulabel">Status</span>
              {project
                ? <StatusBadge status={project.status} />
                : <StatusBadge status={
                    isFinished
                      ? (hasFailed ? 'failed' : isCancelled ? 'cancelled' : 'done')
                      : wsStatus === 'connecting' ? 'queued' : 'running'
                  } />
              }
            </div>

            <hr className="panel__rule" />

            <div className="bp-summary__row">
              <span className="ulabel">Steps</span>
              {/* The completed count is the number the user is actually
                  waiting on. It ticks perhaps nine times in eight minutes, so
                  each tick gets the same small spring the step markers use —
                  the two are reporting the same event. */}
              <span className="figure figure--md">
                <AnimatePresence mode="wait" initial={false}>
                  <motion.span
                    key={stepsComplete}
                    variants={popIn}
                    initial="hidden"
                    animate="visible"
                    exit="exit"
                    className="bp-summary__count"
                  >
                    {stepsComplete}
                  </motion.span>
                </AnimatePresence>
                <span className="figure__unit">/ {totalSteps}</span>
              </span>
            </div>

            {/* Elapsed, ETA and queue position all come from
                `/jobs/{id}/status`, which has always returned them and which
                nothing on this page used to read. */}
            {meta.elapsedSeconds != null && (
              <>
                <hr className="panel__rule" />
                <div className="bp-summary__row">
                  <span className="ulabel">Elapsed</span>
                  <span className="figure figure--sm">{formatDuration(meta.elapsedSeconds)}</span>
                </div>
              </>
            )}

            {!isFinished && meta.remainingSeconds != null && (
              <>
                <hr className="panel__rule" />
                <div className="bp-summary__row">
                  <span className="ulabel">Est. remaining</span>
                  <span className="figure figure--sm">~{formatDuration(meta.remainingSeconds)}</span>
                </div>
              </>
            )}

            {!isFinished && meta.queuePosition != null && (
              <>
                <hr className="panel__rule" />
                <div className="bp-summary__row">
                  <span className="ulabel">Queue position</span>
                  <span className="figure figure--sm">{meta.queuePosition}</span>
                </div>
              </>
            )}
          </motion.div>

          {/* Actions. One column of buttons, each full width, ordered by
              likelihood of use rather than by when the state was added. */}
          {(hasSucceeded || !isFinished) && (
            <motion.div className="bp-actions" variants={appItem}>
              {hasSucceeded && (
                <Link to={`/projects/${id}`} className="btn btn-primary bp-btn">
                  <ExternalLink size={15} /> View result
                </Link>
              )}
              {!isFinished && (
                <button
                  className="btn btn-danger bp-btn"
                  onClick={handleCancel}
                  title="Stop the pipeline at its current step"
                >
                  <X size={15} /> Cancel build
                </button>
              )}
            </motion.div>
          )}

          {/*
            The four outcome notes are mutually exclusive by construction, so
            one <AnimatePresence> covers all of them and the enter of the next
            one cannot start before the previous has left. Each carries a
            stable `key`, which is what lets Framer tell "the note changed"
            from "the note re-rendered".

            These arrive minutes after mount, long after the aside's stagger
            has finished, so each declares its own `initial`/`animate` rather
            than inheriting the parent's — an inherited variant would have
            already been resolved to `visible` and the note would appear with
            no transition at all.
          */}
          <AnimatePresence mode="wait">
          {/* Phase 21: degraded / quota-paused completion notice */}
          {isPartial && (
            <motion.div
              key="partial"
              className="panel panel--pad bp-note bp-note--warn"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0, transition: { duration: DURATION.normal, ease: EASE.out } }}
              exit={{ opacity: 0, transition: { duration: DURATION.instant, ease: EASE.in } }}
            >
              <AlertTriangle size={15} className="bp-note__icon" />
              <div className="bp-note__body">
                <p className="bp-note__title">Finished with a handoff document</p>
                <p className="bp-note__text">
                  {project?.completion_reason
                    ?? 'The build produced usable code but did not complete every step. Your files are downloadable.'}
                </p>
              </div>
            </motion.div>
          )}

          {hasFailed && (
            <motion.div
              key="failed"
              className="panel panel--pad bp-note bp-note--error"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0, transition: { duration: DURATION.normal, ease: EASE.out } }}
              exit={{ opacity: 0, transition: { duration: DURATION.instant, ease: EASE.in } }}
            >
              <X size={15} className="bp-note__icon" />
              <div className="bp-note__body">
                <p className="bp-note__title">What went wrong</p>
                <p className="bp-note__text bp-note__text--mono">{failureText}</p>
                <Link to="/build" className="btn btn-secondary bp-btn bp-note__action">
                  Start a new build
                </Link>
              </div>
            </motion.div>
          )}

          {isCancelled && (
            <motion.div
              key="cancelled"
              className="panel panel--pad bp-note"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0, transition: { duration: DURATION.normal, ease: EASE.out } }}
              exit={{ opacity: 0, transition: { duration: DURATION.instant, ease: EASE.in } }}
            >
              <X size={15} className="bp-note__icon" />
              <div className="bp-note__body">
                <p className="bp-note__title">Cancelled before completion</p>
                <p className="bp-note__text">
                  The pipeline stopped at the step it was on. Partial output is
                  not packaged, so there is nothing to download — start a fresh
                  build when you are ready.
                </p>
                <Link to="/build" className="btn btn-secondary bp-btn bp-note__action">
                  Start a new build
                </Link>
              </div>
            </motion.div>
          )}

          {!isFinished && wsStatus === 'error' && (
            <motion.div
              key="ws-error"
              className="panel panel--pad bp-note bp-note--warn"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0, transition: { duration: DURATION.normal, ease: EASE.out } }}
              exit={{ opacity: 0, transition: { duration: DURATION.instant, ease: EASE.in } }}
            >
              <RadioTower size={15} className="bp-note__icon" />
              <div className="bp-note__body">
                <p className="bp-note__title">Live stream unavailable</p>
                <p className="bp-note__text">
                  Falling back to polling every 5 seconds. The build itself is
                  unaffected.
                </p>
              </div>
            </motion.div>
          )}
          </AnimatePresence>

          {/* Reference, and only while there is waiting to do. */}
          {!isFinished && (
            <motion.div className="panel panel--pad bp-facts" variants={appItem}>
              <span className="ulabel">While you wait</span>
              <dl className="bp-facts__list">
                <div className="bp-facts__item">
                  <dt>Typical run</dt>
                  <dd className="figure figure--sm">3–8<span className="figure__unit">min</span></dd>
                </div>
                <div className="bp-facts__item">
                  <dt>Agents</dt>
                  <dd className="figure figure--sm">9<span className="figure__unit">sequential</span></dd>
                </div>
                <div className="bp-facts__item">
                  <dt>Rotation pause</dt>
                  <dd className="figure figure--sm">2–6<span className="figure__unit">sec</span></dd>
                </div>
              </dl>
              {/* Derived from the health endpoint rather than asserting Groq:
                  the provider is configurable and the copy was a hardcoded
                  claim about it. */}
              <p className="bp-facts__note">
                {health?.llm?.provider
                  ? `${health.llm.provider} keys rotate automatically on a rate limit. `
                  : 'API keys rotate automatically on a rate limit. '}
                A short stall is normal and does not mean the build has stopped.
              </p>
            </motion.div>
          )}
        </motion.aside>
      </div>
    </div>
  );
}
