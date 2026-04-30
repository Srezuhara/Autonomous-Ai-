import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import type { Project } from '../../api/client';
import { StatusBadge } from '../shared/StatusBadge';
import './BuildCard.css';

interface BuildCardProps {
  project: Project;
}

export function BuildCard({ project }: BuildCardProps) {
  const isDone = project.status === 'done';
  const displayName = project.app_name || project.build_id.substring(0, 8).toUpperCase();
  const promptPreview = project.prompt.length > 110
    ? project.prompt.substring(0, 110) + '…'
    : project.prompt;

  return (
    <Link to={`/projects/${project.build_id}`} className="build-card card card--interactive">
      {/* Left: info */}
      <div className="build-card-info">
        <div className="build-card-header">
          <span className="build-card-name">{displayName}</span>
          <StatusBadge status={project.status} />
        </div>
        <p className="build-card-prompt">{promptPreview}</p>
        <div className="build-card-meta">
          <span>{new Date(project.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</span>
          {project.app_type && <span className="tag">{project.app_type}</span>}
          {project.complexity && <span className="tag">{project.complexity}</span>}
          {project.duration_seconds && (
            <span>{Math.round(project.duration_seconds)}s</span>
          )}
        </div>
      </div>

      {/* Middle: scores */}
      {isDone && (
        <div className="build-card-scores">
          <ScoreChip label="Rev" value={project.review_score?.toFixed(1)} />
          <ScoreChip label="Dbg" value={project.debug_score?.split('/')[0]} />
          <ScoreChip label="Tst" value={project.test_score?.split('/')[0]} />
        </div>
      )}

      {/* Right: arrow */}
      <ChevronRight size={18} className="build-card-arrow" />
    </Link>
  );
}

function ScoreChip({ label, value }: { label: string; value?: string | number }) {
  return (
    <div className="score-chip">
      <span className="score-chip-label">{label}</span>
      <span className="score-chip-value">{value ?? '—'}</span>
    </div>
  );
}
