import { useParams, Link, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { RebuildModal } from '../components/shared/RebuildModal';
import {
  ArrowLeft, Download, RefreshCw, Trash2, FileCode2,
  Star, Shield, FlaskConical, Zap, ChevronRight,
  AlertTriangle,
} from 'lucide-react';
import { useProjectDetail } from '../hooks/useQueries';
import { api, isDownloadable } from '../api/client';
import { parseScorePct, scoreColor } from '../lib/scores';
import { formatTokens, formatCost, costOf } from '../lib/pricing';
import { StatusBadge } from '../components/shared/StatusBadge';
import { appItem, appStagger, disclose, EASE, DURATION } from '../lib/motion';
import './ProjectDetail.css';

/**
 * ProjectDetail — the build report.
 *
 * Restructured from a vertical stack of eight equally-weighted cards into
 * three tiers:
 *
 *   1. Header    — what this is, and the three things you can do with it.
 *   2. Readout   — timings, scores and tokens, all in one instrument panel.
 *   3. Evidence  — step logs and the file tree, both collapsed by default.
 *
 * The old page gave a timestamp its own bordered card, the same visual weight
 * as the review score, which flattened the whole screen. Timings are now a
 * mono strip, scores share one panel, and the actions sit in a horizontal
 * toolbar instead of a stacked column pinned to the right of the title.
 */

// ── Score helpers ─────────────────────────────────────────────────────────────
// parseScorePct / scoreColor now live in lib/scores.ts — BuildCard needs the
// same interpretation, and two copies had already drifted apart.

function ScoreGauge({ label, value, icon }: {
  label: string;
  value: string | number | undefined;
  icon: React.ReactNode;
}) {
  const pct     = parseScorePct(value);
  const color   = scoreColor(pct);
  const display = value != null && value !== '' ? String(value) : '—';
  const unset   = display === '—';

  return (
    <div className="score">
      <div className="score__head">
        <span className="score__icon">{icon}</span>
        <span className="ulabel">{label}</span>
      </div>
      <div
        className="score__value figure figure--lg"
        style={unset ? undefined : { color }}
      >
        {display}
      </div>
      <div
        className="meter"
        role="progressbar"
        aria-label={label}
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className="meter__fill" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

// ── Phase 17: Token usage ─────────────────────────────────────────────────────
/**
 * Three display states:
 *   1. All props undefined   → pre-Phase-17 build (no token columns in DB)
 *   2. All props = 0         → build ran after schema migration but no LLM calls recorded
 *   3. total > 0             → normal tracked build — show full stats
 *
 * The hardcoded "llama-3.3-70b" chip that used to sit in this header was
 * removed rather than updated: the frontend receives no model field from the
 * API, so it was asserting a model name it could not know — and that
 * particular one has since been decommissioned. Better to show nothing than
 * to show a confidently wrong label.
 */
function TokenPanel({ promptTokens, completionTokens, totalTokens }: {
  promptTokens?:     number;
  completionTokens?: number;
  totalTokens?:      number;
}) {
  const total      = totalTokens      ?? 0;
  const prompt     = promptTokens     ?? 0;
  const completion = completionTokens ?? 0;

  const prePhase17 = (
    promptTokens     === undefined &&
    completionTokens === undefined &&
    totalTokens      === undefined
  );

  // Rates and formatting are shared with Statistics — see lib/pricing.ts.
  const fmt = (n: number) => formatTokens(n, '—');
  const costLabel = total === 0 ? '—' : formatCost(costOf(prompt, completion));

  const STATS = [
    { label: 'Prompt',     value: fmt(prompt),     accent: false },
    { label: 'Completion', value: fmt(completion), accent: false },
    { label: 'Total',      value: fmt(total),      accent: true  },
    { label: 'Est. cost',  value: costLabel,       accent: false },
  ];

  return (
    <section className="panel panel--pad pd-tokens">
      <header className="pd-tokens__head">
        <Zap size={13} className="pd-tokens__icon" />
        <span className="ulabel">Token usage</span>
        {prePhase17 && <span className="pd-tokens__flag">not tracked</span>}
      </header>

      {prePhase17 ? (
        <p className="pd-empty">
          Token data is recorded for builds run after Phase 17 was deployed.
          Rebuild this project to see usage.
        </p>
      ) : total === 0 ? (
        <p className="pd-empty">
          No tokens recorded — this build may have failed before any LLM calls
          were made, or token tracking was not active for this run.
        </p>
      ) : (
        <dl className="pd-tokens__grid">
          {STATS.map(({ label, value, accent }) => (
            <div key={label} className={`pd-tokens__stat${accent ? ' pd-tokens__stat--accent' : ''}`}>
              <dt className="ulabel">{label}</dt>
              <dd className="figure figure--md">{value}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

// ── Phase 17: Build step log entry ────────────────────────────────────────────
interface StepLog {
  step:   number;
  name:   string;
  status: string;
  at:     string;
  data?:  Record<string, unknown>;
}

function StepLogEntry({ log }: { log: StepLog }) {
  const [open, setOpen] = useState(false);
  const errorType = log.data?.error_type != null ? String(log.data.error_type) : 'Error';
  const errorText = log.data?.error != null ? String(log.data.error) : '';
  const traceback = log.data?.traceback != null ? String(log.data.traceback) : '';
  const hasError  = log.status === 'failed' && errorText.length > 0;
  const hasData   = !!log.data && Object.keys(log.data).length > 0;
  const elapsed   = log.data?.elapsed_seconds as number | undefined;
  const timedOut  = log.data?.timed_out as boolean | undefined;

  const tone =
    log.status === 'done'    ? 'ok'      :
    log.status === 'failed'  ? 'error'   :
    log.status === 'running' ? 'running' :
    'idle';

  return (
    <div className={`logrow${hasError ? ' logrow--error' : ''}`}>
      <button
        type="button"
        className="logrow__head"
        onClick={() => hasData && setOpen(o => !o)}
        disabled={!hasData}
        aria-expanded={hasData ? open : undefined}
      >
        <span className="logrow__n figure">{String(log.step).padStart(2, '0')}</span>
        <span className={`sdot sdot--${tone}`} aria-hidden />
        <span className="logrow__name">{log.name.replace(/_/g, ' ')}</span>

        {timedOut && (
          <span className="logrow__flag">
            <AlertTriangle size={9} /> timeout
          </span>
        )}
        {elapsed != null && (
          <span className="logrow__elapsed figure">
            {elapsed}<span className="figure__unit">s</span>
          </span>
        )}
        <span className={`logrow__status logrow__status--${tone}`}>{log.status}</span>

        {hasData && (
          <motion.span
            className="logrow__chev"
            animate={{ rotate: open ? 90 : 0 }}
            transition={{ duration: DURATION.fast, ease: EASE.out }}
          >
            <ChevronRight size={13} />
          </motion.span>
        )}
      </button>

      {/* Nested inside the step-logs accordion. Framer measures the child's
          height each frame while the parent is also animating to auto, so the
          two stay in step and a row opened during the parent's own reveal does
          not clip. */}
      <AnimatePresence initial={false}>
      {open && hasData && (
        <motion.div
          key="body"
          className="logrow__reveal"
          variants={disclose}
          initial="hidden"
          animate="visible"
          exit="exit"
        >
        <div className="logrow__body">
          {hasError ? (
            <div className="logrow__error">
              <strong>{errorType}:</strong> {errorText}
              {traceback && (
                <pre className="logrow__pre logrow__pre--error">{traceback.slice(-800)}</pre>
              )}
            </div>
          ) : (
            <pre className="logrow__pre">
              {JSON.stringify(
                Object.fromEntries(
                  Object.entries(log.data!).filter(([k]) => k !== 'traceback')
                ),
                null,
                2,
              )}
            </pre>
          )}
        </div>
        </motion.div>
      )}
      </AnimatePresence>
    </div>
  );
}

// ── Main page component ────────────────────────────────────────────────────────
export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: project, isLoading, isError } = useProjectDetail(id);
  const navigate = useNavigate();

  // Rebuild modal state — lives here at page level, NOT inside sub-components
  const [isRebuilding,     setIsRebuilding]     = useState(false);
  const [rebuildModalOpen, setRebuildModalOpen] = useState(false);
  const [logsOpen,         setLogsOpen]         = useState(false);

  const [deleteError, setDeleteError] = useState<string | null>(null);

  /**
   * The `await` here used to be unguarded: a failed delete threw an unhandled
   * rejection, nothing changed on screen, and the user was left looking at a
   * project they had just asked to remove with no idea whether it worked.
   */
  const handleDelete = async () => {
    if (!id || !confirm('Delete this project permanently?')) return;
    setDeleteError(null);
    try {
      await api.deleteProject(id);
      navigate('/dashboard');
    } catch (err) {
      setDeleteError(
        err instanceof Error ? err.message : 'Could not delete this project.'
      );
    }
  };

  /**
   * Called by RebuildModal when the user confirms.
   * customPrompt === '' means "same prompt" (modal's "Same Prompt" mode).
   * customPrompt !== '' means "custom instructions" mode.
   */
  const handleRebuild = async (customPrompt: string) => {
    if (!id || isRebuilding) return;
    setIsRebuilding(true);
    setRebuildModalOpen(false);
    try {
      const res = await api.rebuildProject(id, customPrompt);
      navigate(`/build/${res.new_build_id}`);
    } catch (err) {
      console.error('Rebuild failed:', err);
      setIsRebuilding(false);
    }
  };

  // ── Loading / error guards ────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="project-detail page-wrapper">
        {/* Empty panels at the real heights. The old `.skeleton` shimmered on
            an infinite loop — motion standing in for something that is not
            moving, and the last looping animation left in the app. */}
        <motion.div variants={appStagger(0.06)} initial="hidden" animate="visible" className="pd-skeletons">
          <motion.div variants={appItem} className="panel pd-skeleton" style={{ height: 168 }} />
          <motion.div variants={appItem} className="panel pd-skeleton" style={{ height: 132 }} />
          <motion.div variants={appItem} className="panel pd-skeleton" style={{ height: 200 }} />
        </motion.div>
      </div>
    );
  }

  if (isError || !project) {
    return (
      <div className="project-detail page-wrapper">
        {/* Announced: this replaces a page the user navigated to expecting
            content, and the swap happens after the request resolves. */}
        <div className="panel panel--pad-lg empty" role="alert">
          <FileCode2 size={22} strokeWidth={1.5} className="empty__icon" />
          <h3 className="empty__title">Build not found</h3>
          <p className="empty__body">
            No build exists with this id. It may have been deleted, or the link
            may be from a different instance.
          </p>
          <Link to="/dashboard" className="btn btn-secondary">
            <ArrowLeft size={15} /> Back to dashboard
          </Link>
        </div>
      </div>
    );
  }

  // ── Parse build step logs from the API response ───────────────────────────
  const stepLogs: StepLog[] = (project as unknown as {
    build_steps?: Array<{
      step: number; name: string; status: string; timestamp: string; data?: string;
    }>;
  }).build_steps?.map(s => ({
    step:   s.step,
    name:   s.name,
    status: s.status,
    at:     s.timestamp,
    data:   s.data
      ? (() => { try { return JSON.parse(s.data!); } catch { return {}; } })()
      : undefined,
  })) ?? [];

  const fmtDate = (iso: string) =>
    new Date(iso).toLocaleString([], {
      day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
    });

  const TIMINGS: Array<{ label: string; value: string }> = [
    { label: 'Created', value: fmtDate(project.created_at) },
    ...(project.completed_at
      ? [{ label: 'Completed', value: fmtDate(project.completed_at) }]
      : []),
    ...(project.duration_seconds != null
      ? [{ label: 'Duration', value: `${Math.round(project.duration_seconds)}s` }]
      : []),
  ];

  const downloadable = isDownloadable(project.status);

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    /*
      The report is a stack of independent panels that all arrive together
      when the fetch resolves. Cascading them in reading order — header, then
      banner, then scores, then evidence — turns one wall of boxes into a
      sequence, and it costs 200ms end to end. It runs on mount only; the
      report is static once loaded, so nothing here ever replays.
    */
    <motion.div
      className="project-detail page-wrapper"
      variants={appStagger(0.04)}
      initial="hidden"
      animate="visible"
    >

      <motion.div variants={appItem}>
        <Link to="/dashboard" className="back-link pd-back">
          <ArrowLeft size={14} /> Dashboard
        </Link>
      </motion.div>

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <motion.header className="panel panel--pad-lg pd-header" variants={appItem}>
        <div className="pd-header__top">
          <div className="pd-header__id">
            <h1 className="pd-name">{project.app_name || 'Unnamed app'}</h1>
            <div className="pd-meta">
              <StatusBadge status={project.status} />
              {project.app_type   && <span className="tag">{project.app_type}</span>}
              {project.complexity && <span className="tag">{project.complexity}</span>}
            </div>
          </div>

          {/* Horizontal toolbar. Delete is last and ghost-weighted — a
              destructive action should not be the same size as Download. */}
          <div className="toolbar pd-toolbar">
            {downloadable && (
              <button
                className="btn btn-primary"
                onClick={() => api.downloadZip(id!)}
                id="download-zip-btn"
              >
                <Download size={15} /> Download ZIP
              </button>
            )}
            <button
              className="btn btn-secondary"
              onClick={() => setRebuildModalOpen(true)}
              disabled={isRebuilding}
            >
              {isRebuilding
                ? <><div className="spinner" /> Rebuilding…</>
                : <><RefreshCw size={15} /> Rebuild</>
              }
            </button>
            <button
              className="btn btn-ghost pd-delete"
              onClick={handleDelete}
              aria-label="Delete project"
              title="Delete project"
            >
              <Trash2 size={15} />
            </button>
          </div>
        </div>

        {deleteError && (
          <div className="panel pd-delete-error" role="alert">
            <AlertTriangle size={15} className="pd-delete-error__icon" />
            <p>{deleteError}</p>
          </div>
        )}

        {/* The prompt is the thing that produced everything below it, so it is
            set as a quotation rather than as body copy in a grey block. */}
        <blockquote className="pd-prompt">{project.prompt}</blockquote>

        <dl className="pd-timings">
          {TIMINGS.map(({ label, value }) => (
            <div key={label} className="pd-timings__item">
              <dt className="ulabel">{label}</dt>
              <dd className="figure figure--sm">{value}</dd>
            </div>
          ))}
        </dl>
      </motion.header>

      {/* Phase 21: explain a degraded / quota-paused completion */}
      {project.status === 'done_with_context' && (
        <motion.section className="panel panel--pad pd-banner" variants={appItem}>
          <AlertTriangle size={16} className="pd-banner__icon" />
          <div className="pd-banner__body">
            <p className="pd-banner__title">This build finished with a handoff document.</p>
            <p className="pd-banner__text">
              {project.completion_reason ||
                'The build produced usable code but did not complete every verification step.'}
              {project.progress_percent != null &&
                ` (${Math.round(project.progress_percent)}% of the pipeline completed.)`}
            </p>
            <p className="pd-banner__text">
              Download the ZIP and read <code>SESSION_CONTEXT.md</code> — it lists what
              was generated, what is missing, and how to finish the build.
            </p>
          </div>
        </motion.section>
      )}

      {/* ── Readout ─────────────────────────────────────────────────────── */}
      {downloadable && (
        <motion.section className="panel panel--pad pd-scores" variants={appItem}>
          <ScoreGauge label="Review"  value={project.review_score} icon={<Star size={13} />} />
          <ScoreGauge label="Debug"   value={project.debug_score}  icon={<Shield size={13} />} />
          <ScoreGauge label="Tests"   value={project.test_score}   icon={<FlaskConical size={13} />} />
        </motion.section>
      )}

      <motion.div variants={appItem}>
      <TokenPanel
        promptTokens={project.prompt_tokens}
        completionTokens={project.completion_tokens}
        totalTokens={project.total_tokens}
      />
      </motion.div>

      {/* ── Evidence ────────────────────────────────────────────────────── */}
      {stepLogs.length > 0 && (
        <motion.section className="panel pd-logs" variants={appItem}>
          <button
            type="button"
            className="pd-disclosure"
            onClick={() => setLogsOpen(o => !o)}
            aria-expanded={logsOpen}
          >
            <span className="ulabel">Step logs</span>
            <span className="pd-disclosure__count figure">{stepLogs.length}</span>
            {/* One chevron rotated, not two glyphs swapped. A chevron that
                turns is the disclosure's state made continuous — the user can
                see it is the same control pointing somewhere else, which two
                separate icons cross-fading never quite communicates. */}
            <motion.span
              className="pd-disclosure__chev"
              animate={{ rotate: logsOpen ? 90 : 0 }}
              transition={{ duration: DURATION.fast, ease: EASE.out }}
            >
              <ChevronRight size={15} />
            </motion.span>
          </button>

          {/* The one true accordion on this screen. `disclose` animates height
              to auto, so the panel below is pushed down rather than being
              jumped down — with 9 step logs that is several hundred pixels of
              movement, and without it the page appears to teleport. */}
          <AnimatePresence initial={false}>
            {logsOpen && (
              <motion.div
                key="logs"
                className="pd-logs__reveal"
                variants={disclose}
                initial="hidden"
                animate="visible"
                exit="exit"
              >
                <div className="pd-logs__body">
                  {stepLogs.map(log => <StepLogEntry key={log.step} log={log} />)}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.section>
      )}

      {project.files && project.files.length > 0 && (
        <motion.section className="panel pd-files" variants={appItem}>
          <header className="pd-files__head">
            <FileCode2 size={13} className="pd-files__icon" />
            <span className="ulabel">Generated files</span>
            <span className="pd-disclosure__count figure">{project.files.length}</span>
          </header>
          <div className="pd-tree">
            {project.files.map((f, i) => {
              const path = typeof f === 'string'
                ? f
                : (f as { file_path?: string }).file_path ?? String(f);
              const slash = path.lastIndexOf('/');
              const dir   = slash >= 0 ? path.slice(0, slash + 1) : '';
              const name  = slash >= 0 ? path.slice(slash + 1) : path;

              return (
                // Directory prefix is dimmed and the filename is not, so a
                // 60-file tree can be scanned by name instead of by full path.
                <code key={i} className="pd-tree__row">
                  {dir && <span className="pd-tree__dir">{dir}</span>}
                  <span className="pd-tree__file">{name}</span>
                </code>
              );
            })}
          </div>
        </motion.section>
      )}

      {/*
        ── RebuildModal ──────────────────────────────────────────────────────
        Rendered at the PAGE ROOT — never inside a sub-component like ScoreGauge.
        This is what caused the black screen: the modal was inside ScoreGauge
        but referenced state (rebuildModalOpen, handleRebuild, project, isRebuilding)
        that only exists in ProjectDetail's scope.
      */}
      <RebuildModal
        isOpen={rebuildModalOpen}
        onClose={() => setRebuildModalOpen(false)}
        onRebuild={handleRebuild}
        originalPrompt={project.prompt}
        appName={project.app_name || project.build_id.substring(0, 8)}
        isRebuilding={isRebuilding}
      />
    </motion.div>
  );
}
