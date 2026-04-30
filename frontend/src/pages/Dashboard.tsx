import { useState } from 'react';
import { Link } from 'react-router-dom';
import { PlusCircle, RefreshCw, Activity, CheckCircle, XCircle, Clock } from 'lucide-react';
import { useBuilds, useStats } from '../hooks/useQueries';
import { BuildCard } from '../components/shared/BuildCard';
import './Dashboard.css';

const STATUS_FILTERS = ['all', 'running', 'done', 'failed'] as const;

function MetricCard({ icon, value, label, color }: {
  icon: React.ReactNode;
  value: string | number;
  label: string;
  color: string;
}) {
  return (
    <div className="metric-card card">
      <div className="metric-card-icon" style={{ color }}>
        {icon}
      </div>
      <div className="metric-value">{value}</div>
      <div className="metric-label">{label}</div>
    </div>
  );
}

export default function Dashboard() {
  const [filter, setFilter] = useState<string>('all');
  const { data, isLoading, isError, refetch, isFetching } = useBuilds(
    filter === 'all' ? undefined : filter
  );
  const { data: stats } = useStats();

  return (
    <div className="dashboard page-wrapper animate-in">
      {/* Page Header */}
      <div className="dashboard-header">
        <div>
          <h1 className="dashboard-title">Dashboard</h1>
          <p className="dashboard-subtitle">Monitor and manage your AI-generated applications</p>
        </div>
        <div className="dashboard-actions">
          <button
            className="btn btn-ghost btn-icon"
            onClick={() => refetch()}
            disabled={isFetching}
            aria-label="Refresh"
          >
            <RefreshCw size={16} className={isFetching ? 'spin-icon' : ''} />
          </button>
          <Link to="/build" className="btn btn-primary">
            <PlusCircle size={16} />
            New Build
          </Link>
        </div>
      </div>

      {/* Metrics Row */}
      {stats && (
        <div className="dashboard-metrics">
          <MetricCard
            icon={<Activity size={20} />}
            value={stats.total_builds}
            label="Total Builds"
            color="var(--color-info)"
          />
          <MetricCard
            icon={<CheckCircle size={20} />}
            value={`${stats.success_rate_percent.toFixed(1)}%`}
            label="Success Rate"
            color="var(--color-success)"
          />
          <MetricCard
            icon={<Clock size={20} />}
            value={`${Math.round(stats.avg_duration_seconds)}s`}
            label="Avg Duration"
            color="var(--color-warning)"
          />
          <MetricCard
            icon={<XCircle size={20} />}
            value={Object.keys(stats.top_app_types)[0] ?? '—'}
            label="Top App Type"
            color="var(--color-accent-secondary)"
          />
        </div>
      )}

      {/* Filters + List */}
      <div className="dashboard-body">
        <div className="dashboard-controls">
          <div className="tab-group" role="tablist">
            {STATUS_FILTERS.map(f => (
              <button
                key={f}
                role="tab"
                aria-selected={filter === f}
                className={`tab${filter === f ? ' active' : ''}`}
                onClick={() => setFilter(f)}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
          {data && (
            <span className="dashboard-count">
              {data.projects.length} project{data.projects.length !== 1 ? 's' : ''}
            </span>
          )}
        </div>

        <div className="build-list">
          {isLoading && (
            <div className="skeleton-stack">
              {Array.from({ length: 4 }, (_, i) => (
                <div key={i} className="skeleton" style={{ height: 88, animationDelay: `${i * 70}ms` }} />
              ))}
            </div>
          )}

          {isError && (
            <div className="empty-state card">
              <XCircle size={36} style={{ color: 'var(--color-error)' }} />
              <h3>Backend Unreachable</h3>
              <p style={{ fontSize: 'var(--text-sm)' }}>
                Make sure the FastAPI server is running on port 8000.
              </p>
              <button className="btn btn-primary" onClick={() => refetch()}>Retry</button>
            </div>
          )}

          {!isLoading && !isError && data?.projects.length === 0 && (
            <div className="empty-state card">
              <PlusCircle size={36} style={{ opacity: 0.3 }} />
              <h3>No builds yet</h3>
              <p style={{ fontSize: 'var(--text-sm)' }}>
                Start your first build to see results here.
              </p>
              <Link to="/build" className="btn btn-primary">Start Building</Link>
            </div>
          )}

          {data?.projects.map(project => (
            <BuildCard key={project.build_id} project={project} />
          ))}
        </div>
      </div>
    </div>
  );
}
