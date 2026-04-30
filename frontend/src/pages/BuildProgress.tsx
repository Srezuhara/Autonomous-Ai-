import { useParams, Link } from 'react-router-dom';
import { Wifi, WifiOff, CheckCircle2, XCircle, ArrowLeft, ExternalLink } from 'lucide-react';
import { useBuildProgress } from '../hooks/useBuildProgress';
import { useProjectDetail } from '../hooks/useQueries';
import { StepTracker } from '../components/shared/StepTracker';
import { StatusBadge } from '../components/shared/StatusBadge';
import './BuildProgress.css';

function WsStatusPill({ status }: { status: string }) {
  const MAP: Record<string, { label: string; cls: string; icon: React.ReactNode }> = {
    connecting: { label: 'Connecting…', cls: 'ws-pill--connecting', icon: <Wifi size={13} /> },
    live:       { label: 'Live',        cls: 'ws-pill--live',       icon: <Wifi size={13} /> },
    done:       { label: 'Completed',   cls: 'ws-pill--done',       icon: <CheckCircle2 size={13} /> },
    error:      { label: 'WS Error',    cls: 'ws-pill--error',      icon: <WifiOff size={13} /> },
  };
  const { label, cls, icon } = MAP[status] ?? MAP.connecting;
  return (
    <div className={`ws-pill ${cls}`}>
      {icon}
      <span>{label}</span>
    </div>
  );
}

export default function BuildProgress() {
  const { id } = useParams<{ id: string }>();
  const { steps, wsStatus } = useBuildProgress(id);
  const { data: project } = useProjectDetail(wsStatus === 'done' ? id : undefined);

  const isFinished = wsStatus === 'done' || wsStatus === 'error';
  const hasFailed = project?.status === 'failed' || wsStatus === 'error';

  return (
    <div className="build-progress page-wrapper animate-in">
      {/* Header */}
      <Link to="/dashboard" className="back-link">
        <ArrowLeft size={15} /> Dashboard
      </Link>

      <div className="bp-header">
        <div className="bp-title-row">
          <div>
            <h1 className="bp-title">Building Your App</h1>
            <code className="bp-build-id">{id}</code>
          </div>
          <WsStatusPill status={wsStatus} />
        </div>
      </div>

      {/* Layout */}
      <div className="bp-layout">
        {/* Main tracker */}
        <div className="bp-main card">
          <p className="section-label" style={{ marginBottom: 'var(--space-4)' }}>Pipeline Progress</p>
          <StepTracker steps={steps} totalSteps={9} />
        </div>

        {/* Sidebar */}
        <div className="bp-sidebar">
          {/* Status */}
          <div className="bp-info-card card">
            <span className="section-label">Status</span>
            {project
              ? <StatusBadge status={project.status} />
              : <StatusBadge status={wsStatus === 'connecting' ? 'queued' : 'running'} />
            }
          </div>

          {/* Step count */}
          <div className="bp-info-card card">
            <span className="section-label">Steps Done</span>
            <div className="bp-step-count">
              <span className="bp-step-num">{steps.filter(s => s.status === 'done').length}</span>
              <span className="bp-step-denom">/ 9</span>
            </div>
          </div>

          {/* View result */}
          {isFinished && !hasFailed && project && (
            <Link to={`/projects/${id}`} className="btn btn-primary" style={{ justifyContent: 'center' }}>
              <ExternalLink size={15} /> View Result
            </Link>
          )}

          {/* Error */}
          {hasFailed && (
            <div className="bp-error card">
              <XCircle size={18} style={{ color: 'var(--color-error)', flexShrink: 0 }} />
              <div>
                <p className="bp-error-title">Build Failed</p>
                <p className="bp-error-sub">Check the step log for details.</p>
              </div>
              <Link to="/build" className="btn btn-secondary" style={{ width: '100%', justifyContent: 'center', marginTop: 'var(--space-2)' }}>
                Try Again
              </Link>
            </div>
          )}

          {/* Tips */}
          {!isFinished && (
            <div className="bp-tips card">
              <p className="section-label" style={{ marginBottom: 'var(--space-3)' }}>While you wait</p>
              <ul className="bp-tips-list">
                <li>Pipeline runs up to 9 agents sequentially</li>
                <li>Groq keys rotate automatically on rate limits</li>
                <li>Ollama is used if all Groq keys are exhausted</li>
                <li>Average build time: 3–8 minutes</li>
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
