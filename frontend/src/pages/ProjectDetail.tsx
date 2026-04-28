import { useParams, Link, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Download, RefreshCw, Trash2, FileCode2, Star, Shield, FlaskConical, Clock, Calendar
} from 'lucide-react';
import { useProjectDetail } from '../hooks/useQueries';
import { api } from '../api/client';
import { StatusBadge } from '../components/BuildCard';
import './ProjectDetail.css';

function ScoreGauge({ label, value, icon }: { label: string; value: string | number | undefined; icon: React.ReactNode }) {
  const num = typeof value === 'string' ? parseFloat(value.split('/')[0]) : (value ?? 0);
  const max = typeof value === 'string' && value.includes('/10') ? 10 : 10;
  const pct = Math.min(100, (num / max) * 100);

  const color = pct >= 70 ? 'var(--success)' : pct >= 40 ? 'var(--warning)' : 'var(--error)';

  return (
    <div className="score-gauge glass-panel">
      <div className="score-gauge-header">
        {icon}
        <span>{label}</span>
      </div>
      <div className="score-gauge-value" style={{ color }}>{value ?? '—'}</div>
      <div className="score-gauge-bar">
        <div className="score-gauge-fill" style={{ width: `${pct}%`, background: color }} />
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
      <div className="project-detail-container animate-fade-in">
        <div className="skeleton-card glass-panel" style={{ height: 180 }} />
        <div className="skeleton-card glass-panel" style={{ height: 120 }} />
        <div className="skeleton-card glass-panel" style={{ height: 300 }} />
      </div>
    );
  }

  if (isError || !project) {
    return (
      <div className="project-detail-container animate-fade-in">
        <div className="empty-state glass-panel">
          <h3>Project not found</h3>
          <Link to="/dashboard" className="btn-secondary"><ArrowLeft size={16}/> Back</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="project-detail-container animate-fade-in">
      {/* Back */}
      <Link to="/dashboard" className="back-link"><ArrowLeft size={16}/> Dashboard</Link>

      {/* Hero Card */}
      <div className="pd-hero glass-panel">
        <div className="pd-hero-left">
          <div className="pd-app-name">{project.app_name || 'Unnamed App'}</div>
          <p className="pd-prompt">{project.prompt}</p>
          <div className="pd-meta-row">
            <StatusBadge status={project.status} />
            {project.app_type && <span className="meta-tag">{project.app_type}</span>}
            {project.complexity && <span className="meta-tag">{project.complexity}</span>}
          </div>
        </div>
        <div className="pd-hero-actions">
          {project.status === 'done' && (
            <button className="btn-primary" onClick={() => api.downloadZip(id!)} id="download-zip-btn">
              <Download size={16} /> Download ZIP
            </button>
          )}
          <button className="btn-secondary" onClick={handleRebuild}>
            <RefreshCw size={16} /> Rebuild
          </button>
          <button className="btn-secondary danger-btn" onClick={handleDelete}>
            <Trash2 size={16} /> Delete
          </button>
        </div>
      </div>

      {/* Time Info */}
      <div className="pd-time-row">
        <div className="glass-panel pd-time-card">
          <Calendar size={16} className="text-muted-icon" />
          <span>Created: {new Date(project.created_at).toLocaleString()}</span>
        </div>
        {project.completed_at && (
          <div className="glass-panel pd-time-card">
            <Clock size={16} className="text-muted-icon" />
            <span>Completed: {new Date(project.completed_at).toLocaleString()}</span>
          </div>
        )}
        {project.duration_seconds && (
          <div className="glass-panel pd-time-card">
            <Clock size={16} className="text-muted-icon" />
            <span>Duration: {Math.round(project.duration_seconds)}s</span>
          </div>
        )}
      </div>

      {/* Scores */}
      {project.status === 'done' && (
        <div className="pd-scores-grid">
          <ScoreGauge label="Review Score" value={project.review_score} icon={<Star size={16} />} />
          <ScoreGauge label="Debug Score" value={project.debug_score} icon={<Shield size={16} />} />
          <ScoreGauge label="Test Score" value={project.test_score} icon={<FlaskConical size={16} />} />
        </div>
      )}

      {/* File Tree */}
      {project.files && project.files.length > 0 && (
        <div className="glass-panel pd-files">
          <div className="pd-section-title">
            <FileCode2 size={16} />
            Generated Files <span className="file-count">{project.files.length}</span>
          </div>
          <div className="file-tree">
            {project.files.map((f, i) => (
              <div key={i} className="file-row" style={{ animationDelay: `${i * 20}ms` }}>
                <FileCode2 size={14} className="file-icon" />
                <code>{f.file_path}</code>
                {f.file_type && <span className="meta-tag">{f.file_type}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
