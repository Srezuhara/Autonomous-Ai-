import { useState } from 'react';
import {
  ChevronDown, ChevronRight, CheckCircle2, XCircle,
  Loader, Clock, Terminal, AlertTriangle, Info,
  FileCode2, Star, Shield, FlaskConical
} from 'lucide-react';
import type { ProgressStep } from '../../hooks/useBuildProgress';

interface BuildLogsPanelProps {
  steps:       ProgressStep[];
  buildStatus: string;
  buildDone:   boolean;
}

const STEP_META: Record<string, {
  label:       string;
  description: string;
  icon:        React.ReactNode;
  color:       string;
}> = {
  intent_analyzer:    { label: 'Intent Analysis',    description: 'Parsing requirements from your prompt',            icon: <Info size={14} />,         color: '#7C6BFA' },
  planner:            { label: 'Planning',            description: 'Creating ordered build steps',                     icon: <Terminal size={14} />,     color: '#A78BFA' },
  architect:          { label: 'Architecture',        description: 'Designing folder & file structure',                icon: <FileCode2 size={14} />,    color: '#60A5FA' },
  backend_developer:  { label: 'Backend Dev',         description: 'Generating FastAPI Python code',                   icon: <Terminal size={14} />,     color: '#34D399' },
  frontend_generator: { label: 'Frontend Dev',        description: 'Generating HTML/CSS/JavaScript code',             icon: <FileCode2 size={14} />,    color: '#F59E0B' },
  debugger:           { label: 'Debugger',            description: 'Auto-fixing import errors & installing packages',  icon: <AlertTriangle size={14} />, color: '#FB923C' },
  reviewer:           { label: 'Code Review',         description: 'Scoring code quality 1–10 per file',              icon: <Star size={14} />,         color: '#F472B6' },
  tester:             { label: 'Test Runner',         description: 'Generating & running pytest tests',               icon: <FlaskConical size={14} />, color: '#22D3EE' },
  documenter:         { label: 'Documentation',       description: 'Writing README.md & SETUP.md',                    icon: <FileCode2 size={14} />,    color: '#A3E635' },
  error:              { label: 'Pipeline Error',      description: 'An unexpected error occurred',                    icon: <XCircle size={14} />,      color: '#EF4444' },
};

function formatDuration(a: string, b?: string): string {
  try {
    const start = new Date(a).getTime();
    const end   = b ? new Date(b).getTime() : Date.now();
    const secs  = Math.round((end - start) / 1000);
    if (secs < 60) return `${secs}s`;
    return `${Math.floor(secs / 60)}m ${secs % 60}s`;
  } catch { return '—'; }
}

function parseStepData(data: unknown): Record<string, unknown> {
  if (!data) return {};
  if (typeof data === 'string') {
    try { return JSON.parse(data); } catch { return { message: data }; }
  }
  if (typeof data === 'object') return data as Record<string, unknown>;
  return {};
}

function StepDataBlock({ data }: { data: unknown }) {
  const parsed = parseStepData(data);
  const entries = Object.entries(parsed).filter(([, v]) => v !== null && v !== undefined);
  if (entries.length === 0) return null;

  return (
    <div className="step-data-block">
      {entries.map(([key, value]) => {
        const label = key.replace(/_/g, ' ');
        let display: React.ReactNode = String(value);

        if (key === 'error' || key === 'message') {
          display = (
            <span className="step-data-error">{String(value)}</span>
          );
        } else if (key === 'files_generated' || key === 'files_count') {
          display = <span className="step-data-badge">{String(value)} files</span>;
        } else if (key === 'avg_score' || key === 'score') {
          const n = parseFloat(String(value));
          const color = n >= 7 ? 'var(--color-success)' : n >= 5 ? 'var(--color-warning)' : 'var(--color-error)';
          display = <span style={{ color, fontWeight: 600 }}>{value}/10</span>;
        } else if (key === 'passed' && typeof value === 'number') {
          const total = (parsed.total as number) || 0;
          const color = value === total ? 'var(--color-success)' : 'var(--color-warning)';
          display = <span style={{ color, fontWeight: 600 }}>{value}/{total}</span>;
        } else if (key === 'intent') {
          const intent = value as Record<string, unknown>;
          display = (
            <div className="step-data-intent">
              {intent.app_name && <span className="step-data-badge">{String(intent.app_name)}</span>}
              {intent.app_type && <span className="step-data-tag">{String(intent.app_type)}</span>}
              {intent.complexity && <span className="step-data-tag">{String(intent.complexity)}</span>}
            </div>
          );
        } else if (key === 'steps_count') {
          display = <span className="step-data-badge">{String(value)} steps planned</span>;
        }

        if (key === 'total' && parsed.passed !== undefined) return null; // skip — shown with passed

        return (
          <div key={key} className="step-data-row">
            <span className="step-data-key">{label}</span>
            <span className="step-data-val">{display}</span>
          </div>
        );
      })}
    </div>
  );
}

function StepCard({
  step,
  nextStep,
  isLast,
}: {
  step:     ProgressStep;
  nextStep?: ProgressStep;
  isLast:  boolean;
}) {
  const [expanded, setExpanded] = useState(step.status === 'failed');
  const meta = STEP_META[step.step_name] ?? {
    label:       step.step_name.replace(/_/g, ' '),
    description: '',
    icon:        <Terminal size={14} />,
    color:       '#7C6BFA',
  };

  const duration = nextStep?.timestamp
    ? formatDuration(step.timestamp, nextStep.timestamp)
    : step.status === 'done' || step.status === 'failed'
    ? formatDuration(step.timestamp)
    : null;

  const hasData = step.data && Object.keys(parseStepData(step.data)).length > 0;

  return (
    <div className={`step-card step-card--${step.status}`}>
      {/* Connector line */}
      {!isLast && <div className="step-card-line" style={{ background: step.status === 'done' ? meta.color + '40' : 'var(--border-subtle)' }} />}

      {/* Header */}
      <button
        className="step-card-header"
        onClick={() => setExpanded(!expanded)}
        disabled={!hasData && step.status !== 'failed'}
      >
        {/* Status icon */}
        <div className="step-card-icon" style={{ borderColor: meta.color + '40', background: meta.color + '15' }}>
          {step.status === 'done'    && <CheckCircle2 size={14} style={{ color: meta.color }} />}
          {step.status === 'failed'  && <XCircle      size={14} style={{ color: 'var(--color-error)' }} />}
          {step.status === 'running' && <Loader       size={14} style={{ color: meta.color }} className="spin-icon" />}
        </div>

        {/* Step info */}
        <div className="step-card-info">
          <div className="step-card-title-row">
            <span className="step-card-num">Step {step.step}</span>
            <span className="step-card-name">{meta.label}</span>
            {step.status === 'failed' && (
              <span className="step-card-failed-badge">FAILED</span>
            )}
          </div>
          {meta.description && (
            <span className="step-card-desc">{meta.description}</span>
          )}
        </div>

        {/* Right */}
        <div className="step-card-right">
          {duration && (
            <span className="step-card-duration">
              <Clock size={11} /> {duration}
            </span>
          )}
          {hasData && (
            expanded
              ? <ChevronDown size={14} style={{ color: 'var(--text-tertiary)' }} />
              : <ChevronRight size={14} style={{ color: 'var(--text-tertiary)' }} />
          )}
        </div>
      </button>

      {/* Expanded data */}
      {expanded && (hasData || step.status === 'failed') && (
        <div className="step-card-body">
          {hasData
            ? <StepDataBlock data={step.data} />
            : <p className="step-card-no-data">No additional details available.</p>
          }
          {step.status === 'failed' && (
            <div className="step-card-failure-note">
              <AlertTriangle size={13} />
              <span>This step failed. The pipeline was halted at this point. Check the error details above and try rebuilding.</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function BuildLogsPanel({ steps, buildStatus, buildDone }: BuildLogsPanelProps) {
  const [showAll, setShowAll] = useState(false);

  const sortedSteps = [...steps].sort((a, b) => a.step - b.step);
  const failedSteps = sortedSteps.filter(s => s.status === 'failed');
  const visibleSteps = showAll ? sortedSteps : sortedSteps;

  if (steps.length === 0) {
    return (
      <div className="build-logs-empty">
        <Loader size={20} className="spin-icon" style={{ color: 'var(--text-tertiary)' }} />
        <p>Waiting for pipeline to start…</p>
      </div>
    );
  }

  return (
    <div className="build-logs-panel">
      {/* Summary bar */}
      <div className="logs-summary">
        <div className="logs-summary-left">
          <span className="logs-summary-count">
            {sortedSteps.filter(s => s.status === 'done').length} / {sortedSteps.length} steps completed
          </span>
          {failedSteps.length > 0 && (
            <span className="logs-summary-failed">
              <XCircle size={12} />
              {failedSteps.length} failed
            </span>
          )}
          {buildDone && buildStatus === 'done' && (
            <span className="logs-summary-success">
              <CheckCircle2 size={12} />
              Build successful
            </span>
          )}
        </div>
        <span className="logs-summary-hint">
          {steps.some(s => parseStepData(s.data) && Object.keys(parseStepData(s.data)).length > 0)
            ? 'Click a step to expand details'
            : ''}
        </span>
      </div>

      {/* Step cards */}
      <div className="step-cards-list">
        {visibleSteps.map((step, idx) => (
          <StepCard
            key={step.step}
            step={step}
            nextStep={visibleSteps[idx + 1]}
            isLast={idx === visibleSteps.length - 1}
          />
        ))}

        {/* Pending steps placeholder */}
        {!buildDone && sortedSteps.length < 9 && (
          <div className="step-card-pending-placeholder">
            <span className="step-pending-dot" />
            <span style={{ fontSize: '0.8125rem', color: 'var(--text-tertiary)' }}>
              {9 - sortedSteps.length} more step{9 - sortedSteps.length !== 1 ? 's' : ''} pending…
            </span>
          </div>
        )}
      </div>

      <style>{LOGS_CSS}</style>
    </div>
  );
}

const LOGS_CSS = `
.build-logs-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.build-logs-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-10) var(--space-6);
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}

/* Summary */
.logs-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}

.logs-summary-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.logs-summary-count {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-secondary);
  font-family: var(--font-mono);
}

.logs-summary-failed {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--color-error);
  background: var(--color-error-bg);
  padding: 2px 8px;
  border-radius: var(--radius-full);
}

.logs-summary-success {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--color-success);
  background: var(--color-success-bg);
  padding: 2px 8px;
  border-radius: var(--radius-full);
}

.logs-summary-hint {
  font-size: 0.75rem;
  color: var(--text-tertiary);
  font-style: italic;
}

/* Step cards list */
.step-cards-list {
  display: flex;
  flex-direction: column;
  gap: 0;
  position: relative;
}

/* Individual step card */
.step-card {
  position: relative;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  overflow: hidden;
  margin-bottom: 6px;
  transition: border-color 0.15s ease;
}

.step-card:last-child { margin-bottom: 0; }

.step-card--done    { border-color: rgba(255,255,255,0.08); }
.step-card--running { border-color: var(--border-accent); box-shadow: 0 0 0 1px var(--border-accent); }
.step-card--failed  { border-color: rgba(239,68,68,0.3); }
.step-card--pending { opacity: 0.4; }

.step-card-line {
  position: absolute;
  left: 26px;
  top: 100%;
  width: 2px;
  height: 6px;
  z-index: 1;
}

.step-card-header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 12px 14px;
  background: none;
  border: none;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s ease;
}

.step-card-header:hover:not(:disabled) {
  background: var(--color-bg-hover);
}

.step-card-header:disabled { cursor: default; }

.step-card-icon {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  border: 1px solid;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.step-card-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.step-card-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.step-card-num {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

.step-card-name {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-primary);
}

.step-card-failed-badge {
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: var(--color-error);
  background: var(--color-error-bg);
  border: 1px solid rgba(239,68,68,0.25);
  padding: 1px 6px;
  border-radius: 4px;
}

.step-card-desc {
  font-size: 0.75rem;
  color: var(--text-tertiary);
  line-height: 1.4;
}

.step-card-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.step-card-duration {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 0.75rem;
  font-family: var(--font-mono);
  color: var(--text-tertiary);
}

/* Expanded body */
.step-card-body {
  padding: 0 14px 14px;
  border-top: 1px solid var(--border-subtle);
  margin-top: 0;
  animation: expandIn 0.2s ease-out;
}

@keyframes expandIn {
  from { opacity: 0; transform: translateY(-4px); }
  to   { opacity: 1; transform: translateY(0); }
}

.step-card-no-data {
  font-size: 0.8125rem;
  color: var(--text-tertiary);
  padding: var(--space-3) 0;
  margin: 0;
}

.step-card-failure-note {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  margin-top: var(--space-3);
  padding: var(--space-3) var(--space-3);
  background: var(--color-error-bg);
  border: 1px solid rgba(239,68,68,0.2);
  border-radius: var(--radius-sm);
  font-size: 0.8125rem;
  color: var(--color-error);
  line-height: 1.5;
}

.step-card-failure-note svg { flex-shrink: 0; margin-top: 1px; }

/* Data block */
.step-data-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--space-3) 0 0;
}

.step-data-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-4);
  font-size: 0.8125rem;
}

.step-data-key {
  min-width: 110px;
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: capitalize;
  letter-spacing: 0.02em;
  flex-shrink: 0;
  padding-top: 1px;
}

.step-data-val {
  color: var(--text-secondary);
  line-height: 1.5;
  word-break: break-word;
}

.step-data-error {
  color: var(--color-error);
  font-family: var(--font-mono);
  font-size: 0.8rem;
  background: var(--color-error-bg);
  padding: 4px 8px;
  border-radius: 6px;
  display: block;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 120px;
  overflow-y: auto;
}

.step-data-badge {
  display: inline-flex;
  align-items: center;
  background: var(--color-accent-subtle);
  border: 1px solid var(--border-accent);
  color: var(--color-accent-secondary);
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 600;
}

.step-data-tag {
  display: inline-flex;
  background: var(--color-bg-overlay);
  border: 1px solid var(--border-default);
  color: var(--text-secondary);
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 0.8rem;
  margin-left: 4px;
}

.step-data-intent {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}

/* Pending placeholder */
.step-card-pending-placeholder {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 10px 14px;
  opacity: 0.5;
}

.step-pending-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--border-default);
  flex-shrink: 0;
  animation: pendingPulse 1.5s ease-in-out infinite;
}

@keyframes pendingPulse {
  0%, 100% { opacity: 0.3; }
  50%       { opacity: 1; }
}
`;
