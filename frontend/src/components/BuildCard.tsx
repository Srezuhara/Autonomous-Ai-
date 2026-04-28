import { Link } from 'react-router-dom';
import { Play, CheckCircle, XCircle, Clock, ChevronRight } from 'lucide-react';
import type { Project } from '../api/client';
import './BuildCard.css';

interface BuildCardProps {
  project: Project;
}

export function StatusBadge({ status }: { status: string }) {
  let icon = <Clock size={14} />;
  let className = "badge-pending";

  if (status === 'done') {
    icon = <CheckCircle size={14} />;
    className = "badge-done";
  } else if (status === 'failed' || status === 'cancelled') {
    icon = <XCircle size={14} />;
    className = "badge-failed";
  } else if (status === 'running' || status === 'queued') {
    icon = <Play size={14} className="spin-icon" />;
    className = "badge-running";
  }

  return (
    <div className={`status-badge ${className}`}>
      {icon}
      <span>{status.charAt(0).toUpperCase() + status.slice(1)}</span>
    </div>
  );
}

export default function BuildCard({ project }: BuildCardProps) {
  const isDone = project.status === 'done';

  return (
    <Link to={`/projects/${project.build_id}`} className="build-card glass-panel flex-row">
      <div className="build-info">
        <div className="build-header">
          <h3>{project.app_name || project.build_id.substring(0, 8)}</h3>
          <StatusBadge status={project.status} />
        </div>
        <p className="build-prompt">{project.prompt.length > 100 ? project.prompt.substring(0, 100) + '...' : project.prompt}</p>
        
        <div className="build-meta">
          <span>{new Date(project.created_at).toLocaleDateString()}</span>
          {project.app_type && <span className="meta-tag">{project.app_type}</span>}
          {project.duration_seconds && <span>{Math.round(project.duration_seconds)}s</span>}
        </div>
      </div>

      {isDone && (
        <div className="build-scores">
          <div className="score-item">
            <span className="score-label">Rev</span>
            <span className="score-value">{project.review_score?.toFixed(1) || '-'}</span>
          </div>
          <div className="score-item">
            <span className="score-label">Dbg</span>
            <span className="score-value">{project.debug_score?.split('/')[0] || '-'}</span>
          </div>
          <div className="score-item">
            <span className="score-label">Tst</span>
            <span className="score-value">{project.test_score?.split('/')[0] || '-'}</span>
          </div>
        </div>
      )}

      <div className="card-arrow">
        <ChevronRight size={20} />
      </div>
    </Link>
  );
}
