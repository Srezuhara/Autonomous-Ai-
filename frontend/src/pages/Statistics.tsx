import { useState } from 'react';
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend
} from 'recharts';
import { TrendingUp, CheckCircle, Clock, Layers } from 'lucide-react';
import { useStats, useDailyStats } from '../hooks/useQueries';
import './Statistics.css';

const COLORS = ['#6366f1', '#ec4899', '#10b981', '#f59e0b', '#3b82f6', '#8b5cf6'];

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload?.length) {
    return (
      <div className="chart-tooltip">
        <p className="ct-label">{label}</p>
        {payload.map((p: any) => (
          <p key={p.name} style={{ color: p.color }}>
            {p.name}: <strong>{p.value}</strong>
          </p>
        ))}
      </div>
    );
  }
  return null;
};

export default function Statistics() {
  const [days, setDays] = useState(14);
  const { data: stats, isLoading: statsLoading } = useStats();
  const { data: daily, isLoading: dailyLoading } = useDailyStats(days);

  const isLoading = statsLoading || dailyLoading;

  const appTypeData = stats
    ? Object.entries(stats.top_app_types).map(([name, value]) => ({ name, value }))
    : [];

  return (
    <div className="stats-container animate-fade-in">
      <div className="stats-header">
        <div>
          <h1>Statistics</h1>
          <p className="page-subtitle">Platform-wide build analytics and trends</p>
        </div>
        <div className="days-toggle">
          {[7, 14, 30].map(d => (
            <button
              key={d}
              className={`filter-tab ${days === d ? 'active' : ''}`}
              onClick={() => setDays(d)}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {/* KPI Cards */}
      {isLoading ? (
        <div className="stats-row">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="skeleton-card glass-panel" style={{ height: 100 }} />
          ))}
        </div>
      ) : stats && (
        <div className="stats-row">
          <div className="kpi-card glass-panel">
            <Layers size={20} className="kpi-icon text-info" />
            <div className="kpi-value">{stats.total_builds}</div>
            <div className="kpi-label">Total Builds</div>
          </div>
          <div className="kpi-card glass-panel">
            <CheckCircle size={20} className="kpi-icon text-success" />
            <div className="kpi-value">{stats.success_rate_percent.toFixed(1)}%</div>
            <div className="kpi-label">Success Rate</div>
          </div>
          <div className="kpi-card glass-panel">
            <Clock size={20} className="kpi-icon text-warning" />
            <div className="kpi-value">{Math.round(stats.avg_duration_seconds)}s</div>
            <div className="kpi-label">Avg Duration</div>
          </div>
          <div className="kpi-card glass-panel">
            <TrendingUp size={20} className="kpi-icon text-accent" />
            <div className="kpi-value">{appTypeData.length}</div>
            <div className="kpi-label">App Types Built</div>
          </div>
        </div>
      )}

      {/* Charts Grid */}
      <div className="charts-grid">
        {/* Daily Builds - Area */}
        <div className="glass-panel chart-card chart-wide">
          <div className="chart-title">Daily Builds — Last {days} Days</div>
          {daily && daily.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={daily} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                <defs>
                  <linearGradient id="gradSuccess" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
                  </linearGradient>
                  <linearGradient id="gradFailed" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#ef4444" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="date" tick={{ fill: '#666', fontSize: 11 }} tickLine={false} />
                <YAxis tick={{ fill: '#666', fontSize: 11 }} tickLine={false} axisLine={false} />
                <Tooltip content={<CustomTooltip />} />
                <Legend wrapperStyle={{ fontSize: '0.8rem', paddingTop: '12px' }} />
                <Area type="monotone" dataKey="success" stroke="#10b981" fill="url(#gradSuccess)" strokeWidth={2} />
                <Area type="monotone" dataKey="failed" stroke="#ef4444" fill="url(#gradFailed)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="chart-empty">No data yet</div>
          )}
        </div>

        {/* Success vs Failed Bar */}
        <div className="glass-panel chart-card">
          <div className="chart-title">Success vs Failed</div>
          {daily && daily.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={daily} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="date" tick={{ fill: '#666', fontSize: 11 }} tickLine={false} />
                <YAxis tick={{ fill: '#666', fontSize: 11 }} tickLine={false} axisLine={false} />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="success" fill="#10b981" radius={[4,4,0,0]} />
                <Bar dataKey="failed" fill="#ef4444" radius={[4,4,0,0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="chart-empty">No data yet</div>
          )}
        </div>

        {/* App Type Pie */}
        <div className="glass-panel chart-card">
          <div className="chart-title">App Types</div>
          {appTypeData.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie
                  data={appTypeData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={95}
                  paddingAngle={3}
                  dataKey="value"
                  label={({ name, percent }) => `${name} (${(percent ? percent * 100 : 0).toFixed(0)}%)`}
                  labelLine={false}
                >
                  {appTypeData.map((_, index) => (
                    <Cell key={index} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip content={<CustomTooltip />} />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="chart-empty">No data yet</div>
          )}
        </div>
      </div>
    </div>
  );
}
