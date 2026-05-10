import { useParams, Link, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import {
  ArrowLeft, Download, RefreshCw, Trash2, FileCode2,
  Star, Shield, FlaskConical, Clock, Calendar,
  Zap, ChevronDown, ChevronRight, AlertTriangle
} from 'lucide-react';
import { useProjectDetail } from '../hooks/useQueries';
import { api } from '../api/client';
import { StatusBadge } from '../components/shared/StatusBadge';
import './ProjectDetail.css';

/**
 * Smart score parser — handles all formats the API might return:
 *   "7.5"    → 75%    (numeric out of 10)
 *   "7.5/10" → 75%    (explicit /10)
 *   "3/5"    → 60%    (test score fraction)
 *   "0/0 (collection errors)" → 0%
 *   7        → 70%    (bare number)
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
function TokenCard({ promptTokens, completionTokens, totalTokens }: {
  promptTokens?:     number;
  completionTokens?: number;
  totalTokens?:      number;
}) {
  const total = totalTokens ?? 0;
  if (total === 0) return null;

  const fmt = (n: number) =>
    n >= 1_000_000
      ? `${(n / 1_000_000).toFixed(2)}M`
      : n >= 1_000
      ? `${(n / 1_000).toFixed(1)}K`
      : String(n);

  // Rough cost estimate — Groq llama-3.3-70b pricing (as of 2025)
  // $0.59 / 1M input tokens, $0.79 / 1M output tokens
  const inputCost  = ((promptTokens ?? 0)     / 1_000_000) * 0.59;
  const outputCost = ((completionTokens ?? 0) / 1_000_000) * 0.79;
  const totalCost  = inputCost + outputCost;

  return (
    <div className="pd-token-card card">
      <div className="pd-token-header">
        <Zap size={15} style={{ color: 'var(--color-warning)' }} />
        <span>Token Usage</span>
        <span className="pd-token-model">llama-3.3-70b</span>
      </div>
      <div className="pd-token-grid">
        <div className="pd-token-stat">
          <span className="pd-token-label">Prompt</span>
          <span className="pd-token-value">{fmt(promptTokens ?? 0)}</span>
        </div>
        <div className="pd-token-stat">
          <span className="pd-token-label">Completion</span>
          <span className="pd-token-value">{fmt(completionTokens ?? 0)}</span>
        </div>
        <div className="pd-token-stat pd-token-stat--total">
          <span className="pd-token-label">Total</span>
          <span className="pd-token-value pd-token-value--total">{fmt(total)}</span>
        </div>
        <div className="pd-token-stat">
          <span className="pd-token-label">Est. Cost</span>
          <span className="pd-token-value" style={{ color: 'var(--color-success)' }}>
            ${totalCost < 0.01 ? '<$0.01' : totalCost.toFixed(3)}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── Phase 17: Build step log panel ────────────────────────────────────────────
interface StepLog {
  step:   number;
  name:   string;
  status: string;
  at:     string;
  data?:  Record<string, unknown>;
}

function StepLogEntry({ log }: { log: StepLog }) {
  const [open, setOpen] = useState(false);
  const hasError  = log.status === 'failed' && log.data?.error;
  const hasData   = log.data && Object.keys(log.data).length > 0;
  const elapsed   = log.data?.elapsed_seconds as number | undefined;
  const timedOut  = log.data?.timed_out as boolean | undefined;

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

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: project, isLoading, isError } = useProjectDetail(id);
  const navigate = useNavigate();
  const [isRebuilding, setIsRebuilding] = useState(false);
  const [logsOpen, setLogsOpen] = useState(false);

  const handleDelete = async () => {
    if (!id || !confirm('Delete this project permanently?')) return;
    await api.deleteProject(id);
    navigate('/dashboard');
  };

  const handleRebuild = async () => {
    if (!id || isRebuilding) return;
    setIsRebuilding(true);
    try {
      const res = await api.rebuildProject(id);
      navigate(`/build/${res.new_build_id}`);
    } catch (err) {
      console.error('Rebuild failed:', err);
      setIsRebuilding(false);
    }
  };

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

  // Build step logs from progress (stored in project.progress if available)
  // The API returns them via useProjectDetail → GET /projects/{id}
  // For now we read from JobStatus shape if present; extend when API exposes them.
  const stepLogs: StepLog[] = (project as unknown as {
    build_steps?: Array<{ step: number; name: string; status: string; timestamp: string; data?: string }>
  }).build_steps?.map(s => ({
    step:   s.step,
    name:   s.name,
    status: s.status,
    at:     s.timestamp,
    data:   s.data ? (() => { try { return JSON.parse(s.data!); } catch { return {}; } })() : undefined,
  })) ?? [];

  return (
    <div className="project-detail page-wrapper animate-in">
      {/* Back */}
      <Link to="/dashboard" className="back-link">
        <ArrowLeft size={15} /> Dashboard
      </Link>

      {/* Hero */}
      <div className="pd-hero card">
        <div className="pd-hero-left">
          <h1 className="pd-app-name">{project.app_name || 'Unnamed App'}</h1>
          <p className="pd-prompt">{project.prompt}</p>
          <div className="pd-tags">
            <StatusBadge status={project.status} />
            {project.app_type  && <span className="tag">{project.app_type}</span>}
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
          <button
            className="btn btn-secondary"
            onClick={handleRebuild}
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

      {/* Time info */}
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

      {/* Scores */}
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

      {/* Phase 17: Token usage */}
      <TokenCard
        promptTokens={project.prompt_tokens}
        completionTokens={project.completion_tokens}
        totalTokens={project.total_tokens}
      />

      {/* Phase 17: Build step logs */}
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

      {/* File Tree */}
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
                  {typeof f === 'string' ? f : (f as { file_path?: string }).file_path ?? String(f)}
                </code>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
