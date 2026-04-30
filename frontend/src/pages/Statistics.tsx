import { useState } from 'react';
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend
} from 'recharts';
import { TrendingUp, CheckCircle, Clock, Layers } from 'lucide-react';
import { useStats, useDailyStats } from '../hooks/useQueries';
import './Statistics.css';

const PALETTE = ['#7C6BFA', '#A78BFA', '#22C55E', '#F59E0B', '#3B82F6', '#EC4899'];

function ChartTooltip({ active, payload, label }: {
  active?: boolean;
  payload?: { name: string; value: number; color: string }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <p className="chart-tooltip-label">{label}</p>
      {payload.map(p => (
        <p key={p.name} style={{ color: p.color }} className="chart-tooltip-row">
          <span>{p.name}</span>
          <strong>{p.value}</strong>
        </p>
      ))}
    </div>
  );
}

const AXIS_PROPS = {
  tick: { fill: 'var(--text-tertiary)', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' },
  tickLine: false,
  axisLine: false,
};

const GRID_PROPS = {
  strokeDasharray: '3 3',
  stroke: 'rgba(255,255,255,0.04)',
};

export default function Statistics() {
  const [days, setDays] = useState(14);
  const { data: stats, isLoading: statsLoading } = useStats();
  const { data: dailyRaw, isLoading: dailyLoading } = useDailyStats(days);

  const isLoading = statsLoading || dailyLoading;

  // useDailyStats may return { days, data } or array — handle both
  const daily = Array.isArray(dailyRaw)
    ? dailyRaw
    : (dailyRaw as { data?: unknown[] } | null)?.data ?? [];

  const appTypeData = stats
    ? (Array.isArray(stats.top_app_types)
        ? stats.top_app_types.map((t: { type: string; count: number }) => ({ name: t.type, value: t.count }))
        : Object.entries(stats.top_app_types as Record<string, number>).map(([name, value]) => ({ name, value }))
      )
    : [];

  const METRICS = stats
    ? [
        { icon: <Layers size={18} />, value: stats.total_builds, label: 'Total Builds', color: 'var(--color-info)' },
        { icon: <CheckCircle size={18} />, value: `${stats.success_rate_percent.toFixed(1)}%`, label: 'Success Rate', color: 'var(--color-success)' },
        { icon: <Clock size={18} />, value: `${Math.round(stats.avg_duration_seconds)}s`, label: 'Avg Duration', color: 'var(--color-warning)' },
        { icon: <TrendingUp size={18} />, value: appTypeData.length, label: 'App Types Built', color: 'var(--color-accent-secondary)' },
      ]
    : [];

  return (
    <div className="statistics page-wrapper animate-in">
      {/* Header */}
      <div className="stats-header">
        <div>
          <h1 className="stats-title">Statistics</h1>
          <p className="stats-subtitle">Platform-wide build analytics and trends</p>
        </div>
        <div className="tab-group">
          {[7, 14, 30].map(d => (
            <button
              key={d}
              className={`tab${days === d ? ' active' : ''}`}
              onClick={() => setDays(d)}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {/* KPI Row */}
      {isLoading ? (
        <div className="stats-metrics">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="skeleton" style={{ height: 100 }} />
          ))}
        </div>
      ) : stats && (
        <div className="stats-metrics">
          {METRICS.map(m => (
            <div key={m.label} className="stat-metric card">
              <div style={{ color: m.color }}>{m.icon}</div>
              <div className="metric-value">{m.value}</div>
              <div className="metric-label">{m.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Charts */}
      <div className="charts-grid">
        {/* Area — daily builds */}
        <div className="chart-card card chart-card--wide">
          <p className="chart-title">Daily Builds — Last {days} days</p>
          {daily && daily.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={daily as object[]} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="gSuccess" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#22C55E" stopOpacity={0.25}/>
                    <stop offset="95%" stopColor="#22C55E" stopOpacity={0}/>
                  </linearGradient>
                  <linearGradient id="gFailed" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#EF4444" stopOpacity={0.25}/>
                    <stop offset="95%" stopColor="#EF4444" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid {...GRID_PROPS} />
                <XAxis dataKey="date" {...AXIS_PROPS} />
                <YAxis {...AXIS_PROPS} />
                <Tooltip content={<ChartTooltip />} />
                <Legend wrapperStyle={{ fontSize: '0.75rem', paddingTop: '12px' }} />
                <Area type="monotone" dataKey="success" stroke="#22C55E" fill="url(#gSuccess)" strokeWidth={2} />
                <Area type="monotone" dataKey="failed"  stroke="#EF4444" fill="url(#gFailed)"  strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="chart-empty">No data yet</div>
          )}
        </div>

        {/* Bar — success vs failed */}
        <div className="chart-card card">
          <p className="chart-title">Success vs Failed</p>
          {daily && daily.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={daily as object[]} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                <CartesianGrid {...GRID_PROPS} />
                <XAxis dataKey="date" {...AXIS_PROPS} />
                <YAxis {...AXIS_PROPS} />
                <Tooltip content={<ChartTooltip />} />
                <Bar dataKey="success" fill="#22C55E" radius={[4,4,0,0]} />
                <Bar dataKey="failed"  fill="#EF4444" radius={[4,4,0,0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="chart-empty">No data yet</div>
          )}
        </div>

        {/* Pie — app types */}
        <div className="chart-card card">
          <p className="chart-title">App Types</p>
          {appTypeData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={appTypeData}
                  cx="50%" cy="50%"
                  innerRadius={55} outerRadius={88}
                  paddingAngle={3}
                  dataKey="value"
                  label={({ name, percent }) => `${name} ${((percent ?? 0) * 100).toFixed(0)}%`}
                  labelLine={false}
                >
                  {appTypeData.map((_, i) => (
                    <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                  ))}
                </Pie>
                <Tooltip content={<ChartTooltip />} />
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
