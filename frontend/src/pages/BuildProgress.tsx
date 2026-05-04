import { useParams, Link } from 'react-router-dom';
import {
  Wifi, WifiOff, CheckCircle2, XCircle,
  ArrowLeft, ExternalLink, Loader
} from 'lucide-react';
import { useBuildProgress } from '../hooks/useBuildProgress';
import { useProjectDetail } from '../hooks/useQueries';
import { StepTracker } from '../components/shared/StepTracker';
import { StatusBadge } from '../components/shared/StatusBadge';
import './BuildProgress.css';

// ── WS status pill ─────────────────────────────────────────────────────────────
// Important: we never show "WS Error" to the user because a WS failure is an
// implementation detail — the REST polling fallback keeps the UI working.
function WsStatusPill({ status }: { status: string }) {
  type PillConfig = { label: string; cls: string; icon: React.ReactNode };

  const MAP: Record<string, PillConfig> = {
    connecting: {
      label: 'Connecting…',
      cls:   'ws-pill--connecting',
      icon:  <Loader size={13} className="spin-icon" />,
    },
    live: {
      label: 'Live',
      cls:   'ws-pill--live',
      icon:  <Wifi size={13} />,
    },
    done: {
      label: 'Completed',
      cls:   'ws-pill--done',
      icon:  <CheckCircle2 size={13} />,
    },
    // 'error' maps to a neutral "polling" indicator, not a red error badge
    error: {
      label: 'Polling…',
      cls:   'ws-pill--connecting',
      icon:  <Loader size={13} className="spin-icon" />,
    },
  };

  const cfg: PillConfig = MAP[status] ?? MAP.connecting;
  return (
    <div className={`ws-pill ${cfg.cls}`}>
      {cfg.icon}
      <span>{cfg.label}</span>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────
export default function BuildProgress() {
  const { id } = useParams<{ id: string }>();

  // Live progress from WebSocket (+ REST fallback)
  const { steps, wsStatus, buildDone, buildStatus } = useBuildProgress(id);

  // Only fetch the full project record once the build is confirmed done.
  // Previously this was `wsStatus === 'done'` which never triggered when
  // WS errored after rebuild (the connect-to-undefined bug).
  // Now we use `buildDone` which is set by both the WS 'complete' message
  // AND the REST polling fallback.
  const { data: project } = useProjectDetail(buildDone ? id : undefined);

  // ── Derive display state ───────────────────────────────────────────────────
  const isFinished = buildDone;

  // Actual build outcome — use REST project data if available, fall back to
  // the status we got from the WS/polling stream.
  const actualStatus = project?.status ?? buildStatus;

  // ─────────────────────────────────────────────────────────────────────────────
  // IMPORTANT: hasFailed must only be true when the BUILD PIPELINE failed.
  // Previously `hasFailed = wsStatus === 'error'` which meant ANY WebSocket
  // connection problem (including the rebuild-to-undefined bug) showed
  // "Build Failed" permanently — even for builds that succeeded.
  //
  // Now: only show failure UI when the build is done AND the actual server
  // status is 'failed'. A WS drop alone never triggers this.
  // ─────────────────────────────────────────────────────────────────────────────
  const hasFailed    = isFinished && actualStatus === 'failed';
  const hasSucceeded = isFinished && (actualStatus === 'done');

  const stepsComplete = steps.filter(s => s.status === 'done').length;

  return (
    <div className="build-progress page-wrapper animate-in">

      {/* Back link */}
      <Link to="/dashboard" className="back-link">
        <ArrowLeft size={15} /> Dashboard
      </Link>

      {/* Header */}
      <div className="bp-header">
        <div className="bp-title-row">
          <div>
            <h1 className="bp-title">
              {isFinished
                ? (hasFailed ? 'Build Failed' : 'Build Complete!')
                : 'Building Your App'}
            </h1>
            <code className="bp-build-id">{id}</code>
          </div>
          <WsStatusPill status={wsStatus} />
        </div>
      </div>

      {/* Main layout */}
      <div className="bp-layout">

        {/* Step tracker */}
        <div className="bp-main card">
          <p className="section-label" style={{ marginBottom: 'var(--space-4)' }}>
            Pipeline Progress
          </p>
          <StepTracker steps={steps} totalSteps={9} />
        </div>

        {/* Sidebar */}
        <div className="bp-sidebar">

          {/* Status badge */}
          <div className="bp-info-card card">
            <span className="section-label">Status</span>
            {project
              ? <StatusBadge status={project.status} />
              : <StatusBadge status={
                  isFinished
                    ? (hasFailed ? 'failed' : 'done')
                    : wsStatus === 'connecting' ? 'queued' : 'running'
                } />
            }
          </div>

          {/* Step counter */}
          <div className="bp-info-card card">
            <span className="section-label">Steps Done</span>
            <div className="bp-step-count">
              <span className="bp-step-num">{stepsComplete}</span>
              <span className="bp-step-denom">/ 9</span>
            </div>
          </div>

          {/* View result — only shown when build genuinely succeeded */}
          {hasSucceeded && (
            <Link
              to={`/projects/${id}`}
              className="btn btn-primary"
              style={{ justifyContent: 'center' }}
            >
              <ExternalLink size={15} /> View Result
            </Link>
          )}

          {/* Failure card — only shown when build pipeline actually failed */}
          {hasFailed && (
            <div className="bp-error card">
              <XCircle
                size={18}
                style={{ color: 'var(--color-error)', flexShrink: 0 }}
              />
              <div>
                <p className="bp-error-title">Build Failed</p>
                <p className="bp-error-sub">
                  {(project as { error?: string } | undefined)?.error
                    ?? 'Check the step log for details.'}
                </p>
              </div>
              <Link
                to="/build"
                className="btn btn-secondary"
                style={{
                  width: '100%',
                  justifyContent: 'center',
                  marginTop: 'var(--space-2)',
                }}
              >
                Try Again
              </Link>
            </div>
          )}

          {/* Tips — shown while build is running */}
          {!isFinished && (
            <div className="bp-tips card">
              <p className="section-label" style={{ marginBottom: 'var(--space-3)' }}>
                While you wait
              </p>
              <ul className="bp-tips-list">
                <li>Pipeline runs up to 9 agents sequentially</li>
                <li>Groq keys rotate automatically on rate limits</li>
                <li>Short waits (2–6 s) are normal during rotation</li>
                <li>Average build time: 3–8 minutes</li>
              </ul>
            </div>
          )}

          {/* Polling notice — shown when WS dropped but build is still running */}
          {!isFinished && wsStatus === 'error' && (
            <div
              className="bp-tips card"
              style={{ borderColor: 'rgba(245,158,11,0.25)' }}
            >
              <p
                className="section-label"
                style={{ color: 'var(--color-warning)', marginBottom: 'var(--space-2)' }}
              >
                Live stream unavailable
              </p>
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}>
                Polling for updates every 5 s. Build is still running.
              </p>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
