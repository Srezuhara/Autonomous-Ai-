import { useParams, Link, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import { RebuildModal } from '../components/shared/RebuildModal';
import {
  ArrowLeft, Download, RefreshCw, Trash2, FileCode2,
  Star, Shield, FlaskConical, Clock, Calendar,
  Zap, ChevronDown, ChevronRight, AlertTriangle
} from 'lucide-react';
import { useProjectDetail } from '../hooks/useQueries';
import { api } from '../api/client';
import { StatusBadge } from '../components/shared/StatusBadge';
import './ProjectDetail.css';

// ── Score helpers ─────────────────────────────────────────────────────────────
/**
 * Converts any score format to a 0-100 percentage.
 *   "7.5"    → 75%   (numeric out of 10)
 *   "7.5/10" → 75%   (explicit /10)
 *   "3/5"    → 60%   (test score fraction)
 *   "0/0 (collection errors)" → 0%
 *   7        → 70%   (bare number)
 */
function parseScorePct(value: string | number | undefined): number {
  if (value == null) return 0;
  const str = String(value).trim();
  if (!str || str === '—') return 0;

  const fracMatch = str.match(/^(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)/);
  if (fracMatch) {
    const num = parseFloat(fracMatch[1]);
    const den = parseFloat(fracMatch[2]);
    if (den > 0) return Math.min(100, (num / den) * 100);
    return 0;
  }

  const n = parseFloat(str);
  if (!isNaN(n)) return Math.min(100, (n / 10) * 100);
  return 0;
}

// ── ScoreGauge — pure display component, no modal inside ─────────────────────
function ScoreGauge({ label, value, icon }: {
  label: string;
  value: string | number | undefined;
  icon: React.ReactNode;
}) {
  const pct   = parseScorePct(value);
  const color = pct >= 70
    ? 'var(--color-success)'
    : pct >= 40
    ? 'var(--color-warning)'
    : 'var(--color-error)';
  const display = value != null && value !== '' ? String(value) : '—';

  return (
    <div className="score-gauge card">
      <div className="score-gauge-header">
        {icon}
        <span>{label}</span>
      </div>
      <div className="score-gauge-value" style={{ color }}>{display}</div>
      <div className="score-gauge-bar">
        <div
          className="score-gauge-fill"
          style={{ width: `${pct}%`, background: color }}
          role="progressbar"
          aria-valuenow={Math.round(pct)}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>
    </div>
  );
}

// ── Phase 17: Token usage card ─────────────────────────────────────────────────
/**
 * Three display states:
 *   1. All props undefined   → pre-Phase-17 build (no token columns in DB)
 *   2. All props = 0         → build ran after schema migration but no LLM calls recorded
 *   3. total > 0             → normal tracked build — show full stats
 */
function TokenCard({ promptTokens, completionTokens, totalTokens }: {
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

  const fmt = (n: number) =>
    n >= 1_000_000
      ? `${(n / 1_000_000).toFixed(2)}M`
      : n >= 1_000
      ? `${(n / 1_000).toFixed(1)}K`
      : n === 0 ? '—' : String(n);

  const inputCost  = (prompt     / 1_000_000) * 0.59;
  const outputCost = (completion / 1_000_000) * 0.79;
  const totalCost  = inputCost + outputCost;

  const costLabel =
    total === 0    ? '—'
    : totalCost < 0.001 ? '<$0.001'
    : `$${totalCost.toFixed(3)}`;

  return (
    <div className="pd-token-card card">
      <div className="pd-token-header">
        <Zap size={15} style={{ color: 'var(--color-warning)' }} />
        <span>Token usage</span>
        <span className="pd-token-model">llama-3.3-70b</span>
        {prePhase17 && (
          <span style={{
            marginLeft: 'auto',
            fontSize: 'var(--text-xs)',
            color: 'var(--text-tertiary)',
            fontStyle: 'italic',
          }}>
            build predates tracking
          </span>
        )}
      </div>

      {prePhase17 ? (
        <p style={{
          fontSize: 'var(--text-xs)',
          color: 'var(--text-tertiary)',
          margin: 'var(--space-2) 0 0',
          lineHeight: 'var(--leading-relaxed)',
        }}>
          Token data is recorded for builds run after Phase 17 was deployed.
          Rebuild this project to see usage.
        </p>
      ) : total === 0 ? (
        <p style={{
          fontSize: 'var(--text-xs)',
          color: 'var(--text-tertiary)',
          margin: 'var(--space-2) 0 0',
          lineHeight: 'var(--leading-relaxed)',
        }}>
          No tokens recorded — this build may have failed before any LLM calls
          were made, or token tracking was not active for this run.
        </p>
      ) : (
        <div className="pd-token-grid">
          <div className="pd-token-stat">
            <span className="pd-token-label">Prompt</span>
            <span className="pd-token-value">{fmt(prompt)}</span>
          </div>
          <div className="pd-token-stat">
            <span className="pd-token-label">Completion</span>
            <span className="pd-token-value">{fmt(completion)}</span>
          </div>
          <div className="pd-token-stat pd-token-stat--total">
            <span className="pd-token-label">Total</span>
            <span className="pd-token-value pd-token-value--total">{fmt(total)}</span>
          </div>
          <div className="pd-token-stat">
            <span className="pd-token-label">Est. cost</span>
            <span className="pd-token-value" style={{ color: 'var(--color-success)' }}>
              {costLabel}
            </span>
          </div>
        </div>
      )}
    </div>
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
  const hasError = log.status === 'failed' && log.data?.error;
  const hasData  = log.data && Object.keys(log.data).length > 0;
  const elapsed  = log.data?.elapsed_seconds as number | undefined;
  const timedOut = log.data?.timed_out as boolean | undefined;

  const statusColor =
    log.status === 'done'    ? 'var(--color-success)' :
    log.status === 'failed'  ? 'var(--color-error)'   :
    log.status === 'running' ? 'var(--color-info)'    :
    'var(--text-tertiary)';

  return (
    <div className={`step-log-entry${hasError ? ' step-log-entry--error' : ''}`}>
      <div
        className="step-log-header"
        onClick={() => hasData && setOpen(o => !o)}
        style={{ cursor: hasData ? 'pointer' : 'default' }}
      >
        <span className="step-log-num">{log.step}</span>
        <span className="step-log-name">{log.name.replace(/_/g, ' ')}</span>
        {elapsed != null && (
          <span className="step-log-elapsed">{elapsed}s</span>
        )}
        {timedOut && (
          <span className="step-log-badge step-log-badge--timeout">
            <AlertTriangle size={10} /> timeout
          </span>
        )}
        <span className="step-log-status" style={{ color: statusColor }}>
          {log.status}
        </span>
        {hasData && (
          open
            ? <ChevronDown size={13} style={{ color: 'var(--text-tertiary)', marginLeft: 'auto' }} />
            : <ChevronRight size={13} style={{ color: 'var(--text-tertiary)', marginLeft: 'auto' }} />
        )}
      </div>

      {open && hasData && (
        <div className="step-log-body">
          {hasError && (
            <div className="step-log-error">
              <strong>{log.data!.error_type as string}:</strong>{' '}
              {log.data!.error as string}
              {log.data!.traceback && (
                <pre className="step-log-traceback">
                  {(log.data!.traceback as string).slice(-800)}
                </pre>
              )}
            </div>
          )}
          {!hasError && (
            <pre className="step-log-data">
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
      )}
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

  const handleDelete = async () => {
    if (!id || !confirm('Delete this project permanently?')) return;
    await api.deleteProject(id);
    navigate('/dashboard');
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
      <div className="project-detail page-wrapper animate-in">
        <div className="skeleton" style={{ height: 180 }} />
        <div className="skeleton" style={{ height: 80 }} />
        <div className="skeleton" style={{ height: 200 }} />
      </div>
    );
  }

  if (isError || !project) {
    return (
      <div className="project-detail page-wrapper animate-in">
        <div className="empty-state card">
          <h3>Project not found</h3>
          <Link to="/dashboard" className="btn btn-secondary">
            <ArrowLeft size={15} /> Back to Dashboard
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

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="project-detail page-wrapper animate-in">

      {/* Back */}
      <Link to="/dashboard" className="back-link">
        <ArrowLeft size={15} /> Dashboard
      </Link>

      {/* Hero card */}
      <div className="pd-hero card">
        <div className="pd-hero-left">
          <h1 className="pd-app-name">{project.app_name || 'Unnamed App'}</h1>
          <p className="pd-prompt">{project.prompt}</p>
          <div className="pd-tags">
            <StatusBadge status={project.status} />
            {project.app_type   && <span className="tag">{project.app_type}</span>}
            {project.complexity && <span className="tag">{project.complexity}</span>}
          </div>
        </div>

        <div className="pd-actions">
          {project.status === 'done' && (
            <button
              className="btn btn-primary"
              onClick={() => api.downloadZip(id!)}
              id="download-zip-btn"
            >
              <Download size={15} /> Download ZIP
            </button>
          )}

          {/* Rebuild button — opens modal, does NOT immediately start a build */}
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

          <button className="btn btn-danger" onClick={handleDelete}>
            <Trash2 size={15} /> Delete
          </button>
        </div>
      </div>

      {/* Time row */}
      <div className="pd-time-row">
        <div className="pd-time-item card">
          <Calendar size={14} className="pd-time-icon" />
          <span>Created: {new Date(project.created_at).toLocaleString()}</span>
        </div>
        {project.completed_at && (
          <div className="pd-time-item card">
            <Clock size={14} className="pd-time-icon" />
            <span>Completed: {new Date(project.completed_at).toLocaleString()}</span>
          </div>
        )}
        {project.duration_seconds != null && (
          <div className="pd-time-item card">
            <Clock size={14} className="pd-time-icon" />
            <span>Duration: {Math.round(project.duration_seconds)}s</span>
          </div>
        )}
      </div>

      {/* Score gauges — only for completed builds */}
      {project.status === 'done' && (
        <div className="pd-scores">
          <ScoreGauge
            label="Review Score"
            value={project.review_score}
            icon={<Star size={14} />}
          />
          <ScoreGauge
            label="Debug Score"
            value={project.debug_score}
            icon={<Shield size={14} />}
          />
          <ScoreGauge
            label="Test Score"
            value={project.test_score}
            icon={<FlaskConical size={14} />}
          />
        </div>
      )}

      {/* Token usage — always shown, never silently hidden */}
      <TokenCard
        promptTokens={project.prompt_tokens}
        completionTokens={project.completion_tokens}
        totalTokens={project.total_tokens}
      />

      {/* Build step logs */}
      {stepLogs.length > 0 && (
        <div className="pd-step-logs card">
          <button
            className="pd-step-logs-toggle"
            onClick={() => setLogsOpen(o => !o)}
          >
            <span className="section-label">Build Step Logs</span>
            <span className="pd-step-log-count">{stepLogs.length} steps</span>
            {logsOpen
              ? <ChevronDown size={15} style={{ marginLeft: 'auto', color: 'var(--text-tertiary)' }} />
              : <ChevronRight size={15} style={{ marginLeft: 'auto', color: 'var(--text-tertiary)' }} />
            }
          </button>
          {logsOpen && (
            <div className="pd-step-logs-body">
              {stepLogs.map(log => (
                <StepLogEntry key={log.step} log={log} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Generated file tree */}
      {project.files && project.files.length > 0 && (
        <div className="pd-files card">
          <div className="pd-files-header">
            <FileCode2 size={15} />
            <span>Generated Files</span>
            <span className="pd-file-count">{project.files.length}</span>
          </div>
          <div className="file-tree">
            {project.files.map((f, i) => (
              <div
                key={i}
                className="file-row"
                style={{ animationDelay: `${i * 18}ms` }}
              >
                <FileCode2 size={13} className="file-row-icon" />
                <code className="file-row-path">
                  {typeof f === 'string'
                    ? f
                    : (f as { file_path?: string }).file_path ?? String(f)}
                </code>
              </div>
            ))}
          </div>
        </div>
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
    </div>
  );
}
