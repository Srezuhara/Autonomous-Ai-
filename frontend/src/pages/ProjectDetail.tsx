import { useParams, Link, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Download, RefreshCw, Trash2, FileCode2,
  Star, Shield, FlaskConical, Clock, Calendar
} from 'lucide-react';
import { useProjectDetail } from '../hooks/useQueries';
import { api } from '../api/client';
import { StatusBadge } from '../components/shared/StatusBadge';
import './ProjectDetail.css';

function ScoreGauge({ label, value, icon }: {
  label: string;
  value: string | number | undefined;
  icon: React.ReactNode;
}) {
  const raw = typeof value === 'string' ? parseFloat(value.split('/')[0]) : (value ?? 0);
  const pct = Math.min(100, ((raw || 0) / 10) * 100);
  const color = pct >= 70
    ? 'var(--color-success)'
    : pct >= 40
    ? 'var(--color-warning)'
    : 'var(--color-error)';

  return (
    <div className="score-gauge card">
      <div className="score-gauge-header">
        {icon}
        <span>{label}</span>
      </div>
      <div className="score-gauge-value" style={{ color }}>{value ?? '—'}</div>
      <div className="score-gauge-bar">
        <div
          className="score-gauge-fill"
          style={{ width: `${pct}%`, background: color }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>
    </div>
  );
}

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: project, isLoading, isError } = useProjectDetail(id);
  const navigate = useNavigate();

  const handleDelete = async () => {
    if (!id || !confirm('Delete this project permanently?')) return;
    await api.deleteProject(id);
    navigate('/dashboard');
  };

  const handleRebuild = async () => {
    if (!id) return;
    const res = await api.rebuildProject(id);
    navigate(`/build/${res.build_id}`);
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
            {project.app_type && <span className="tag">{project.app_type}</span>}
            {project.complexity && <span className="tag">{project.complexity}</span>}
          </div>
        </div>
        <div className="pd-actions">
          {project.status === 'done' && (
            <button className="btn btn-primary" onClick={() => api.downloadZip(id!)} id="download-zip-btn">
              <Download size={15} /> Download ZIP
            </button>
          )}
          <button className="btn btn-secondary" onClick={handleRebuild}>
            <RefreshCw size={15} /> Rebuild
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
        {project.duration_seconds && (
          <div className="pd-time-item card">
            <Clock size={14} className="pd-time-icon" />
            <span>Duration: {Math.round(project.duration_seconds)}s</span>
          </div>
        )}
      </div>

      {/* Scores */}
      {project.status === 'done' && (
        <div className="pd-scores">
          <ScoreGauge label="Review Score"  value={project.review_score}  icon={<Star size={14} />}         />
          <ScoreGauge label="Debug Score"   value={project.debug_score}   icon={<Shield size={14} />}       />
          <ScoreGauge label="Test Score"    value={project.test_score}    icon={<FlaskConical size={14} />} />
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
                <code className="file-row-path">{f}</code>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
