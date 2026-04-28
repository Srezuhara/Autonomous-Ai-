import { useState } from 'react';
import { Link } from 'react-router-dom';
import { PlusCircle, RefreshCw, Activity, CheckCircle, XCircle, Clock } from 'lucide-react';
import { useBuilds, useStats } from '../hooks/useQueries';
import BuildCard from '../components/BuildCard';
import './Dashboard.css';

const STATUS_FILTERS = ['all', 'running', 'done', 'failed'] as const;

export default function Dashboard() {
  const [filter, setFilter] = useState<string>('all');
  const { data, isLoading, isError, refetch, isFetching } = useBuilds(filter === 'all' ? undefined : filter);
  const { data: stats } = useStats();

  return (
    <div className="dashboard-container animate-fade-in">
      {/* Header */}
      <div className="dashboard-header">
        <div>
          <h1>Dashboard</h1>
          <p className="page-subtitle">Monitor and manage your generated applications</p>
        </div>
        <div className="header-actions">
          <button className="btn-secondary icon-btn" onClick={() => refetch()} disabled={isFetching} title="Refresh">
            <RefreshCw size={16} className={isFetching ? 'spin-icon' : ''} />
          </button>
          <Link to="/build" className="btn-primary">
            <PlusCircle size={18} /> New Build
          </Link>
        </div>
      </div>

      {/* Stats Row */}
      {stats && (
        <div className="stats-row">
          <div className="stat-chip glass-panel">
            <Activity size={18} className="stat-chip-icon text-info" />
            <div>
              <span className="stat-chip-value">{stats.total_builds}</span>
              <span className="stat-chip-label">Total Builds</span>
            </div>
          </div>
          <div className="stat-chip glass-panel">
            <CheckCircle size={18} className="stat-chip-icon text-success" />
            <div>
              <span className="stat-chip-value">{stats.success_rate_percent.toFixed(1)}%</span>
              <span className="stat-chip-label">Success Rate</span>
            </div>
          </div>
          <div className="stat-chip glass-panel">
            <Clock size={18} className="stat-chip-icon text-warning" />
            <div>
              <span className="stat-chip-value">{Math.round(stats.avg_duration_seconds)}s</span>
              <span className="stat-chip-label">Avg Duration</span>
            </div>
          </div>
          <div className="stat-chip glass-panel">
            <XCircle size={18} className="stat-chip-icon text-error" />
            <div>
              <span className="stat-chip-value">
                {Object.entries(stats.top_app_types)[0]?.[0] ?? '—'}
              </span>
              <span className="stat-chip-label">Top App Type</span>
            </div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="filter-tabs">
        {STATUS_FILTERS.map(f => (
          <button
            key={f}
            className={`filter-tab ${filter === f ? 'active' : ''}`}
            onClick={() => setFilter(f)}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {/* Build List */}
      <div className="build-list">
        {isLoading && (
          <div className="skeleton-list">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="skeleton-card glass-panel" style={{ animationDelay: `${i * 80}ms` }} />
            ))}
          </div>
        )}

        {isError && (
          <div className="empty-state glass-panel">
            <XCircle size={40} className="text-error" />
            <h3>Could not reach the backend</h3>
            <p>Make sure the FastAPI server is running on port 8000.</p>
            <button className="btn-primary" onClick={() => refetch()}>Retry</button>
          </div>
        )}

        {!isLoading && !isError && data?.projects.length === 0 && (
          <div className="empty-state glass-panel">
            <PlusCircle size={40} style={{ opacity: 0.4 }} />
            <h3>No builds yet</h3>
            <p>Start your first build to see it appear here.</p>
            <Link to="/build" className="btn-primary">Create Build</Link>
          </div>
        )}

        {data?.projects.map((project) => (
          <BuildCard key={project.build_id} project={project} />
        ))}
      </div>
    </div>
  );
}
