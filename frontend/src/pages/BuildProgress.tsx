import { useParams, Link } from 'react-router-dom';
import { Wifi, WifiOff, CheckCircle2, XCircle, ArrowLeft, ExternalLink } from 'lucide-react';
import { useBuildProgress } from '../hooks/useBuildProgress';
import { useProjectDetail } from '../hooks/useQueries';
import StepTracker from '../components/StepTracker';
import { StatusBadge } from '../components/BuildCard';
import './BuildProgress.css';

function WsStatusPill({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string; icon: React.ReactNode }> = {
    connecting: { label: 'Connecting…', cls: 'ws-connecting', icon: <Wifi size={14} /> },
    live:       { label: 'Live',        cls: 'ws-live',       icon: <Wifi size={14} /> },
    done:       { label: 'Completed',   cls: 'ws-done',       icon: <CheckCircle2 size={14} /> },
    error:      { label: 'WS Error',    cls: 'ws-error',      icon: <WifiOff size={14} /> },
  };
  const { label, cls, icon } = map[status] ?? map.connecting;
  return <div className={`ws-pill ${cls}`}>{icon} {label}</div>;
}

export default function BuildProgress() {
  const { id } = useParams<{ id: string }>();
  const { steps, wsStatus } = useBuildProgress(id);
  const { data: project } = useProjectDetail(wsStatus === 'done' ? id : undefined);

  const isFinished = wsStatus === 'done' || wsStatus === 'error';
  const hasFailed = project?.status === 'failed' || wsStatus === 'error';

  return (
    <div className="build-progress-container animate-fade-in">
      {/* Header */}
      <div className="bp-header">
        <Link to="/dashboard" className="back-link">
          <ArrowLeft size={16} /> Dashboard
        </Link>
        <div className="bp-title-row">
          <div>
            <h1>Building Your App</h1>
            <code className="build-id-label">{id}</code>
          </div>
          <WsStatusPill status={wsStatus} />
        </div>
      </div>

      <div className="bp-layout">
        {/* Main tracker */}
        <div className="bp-main glass-panel">
          <div className="bp-section-title">Pipeline Progress</div>
          <StepTracker steps={steps} totalSteps={9} />
        </div>

        {/* Sidebar */}
        <div className="bp-sidebar">
          {/* Live step count */}
          <div className="glass-panel bp-info-card">
            <div className="bp-info-label">Status</div>
            {project ? (
              <StatusBadge status={project.status} />
            ) : (
              <StatusBadge status={wsStatus === 'connecting' ? 'queued' : 'running'} />
            )}
          </div>

          <div className="glass-panel bp-info-card">
            <div className="bp-info-label">Steps Complete</div>
            <div className="bp-info-value">
              {steps.filter(s => s.status === 'done').length}
              <span className="bp-info-denom"> / 9</span>
            </div>
          </div>

          {isFinished && !hasFailed && project && (
            <Link to={`/projects/${id}`} className="btn-primary w-full">
              <ExternalLink size={16} /> View Result
            </Link>
          )}

          {hasFailed && (
            <div className="bp-error-box glass-panel">
              <XCircle size={20} className="text-error" />
              <p>Build failed. Check the step log above for details.</p>
              <Link to="/build" className="btn-secondary" style={{ width: '100%', justifyContent: 'center' }}>
                Try Again
              </Link>
            </div>
          )}

          {!isFinished && (
            <div className="bp-tips glass-panel">
              <div className="bp-section-title">While you wait…</div>
              <ul>
                <li>The pipeline runs up to 9 agents sequentially</li>
                <li>Groq keys rotate automatically on rate limits</li>
                <li>Ollama is used if all Groq keys are exhausted</li>
                <li>Average build time is 3 – 8 minutes</li>
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
