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

  // API returns { days, data: [...] } — handle both array and wrapped object
  const daily: object[] = Array.isArray(dailyRaw)
    ? dailyRaw
    : (dailyRaw as { data?: object[] } | null)?.data ?? [];

  // Filter out days with zero builds so the chart isn't a flat zero line
  const dailyWithData = daily.filter((d: object) => {
    const row = d as { total?: number };
    return (row.total ?? 0) > 0;
  });

  // Show all days in chart (including zeros) but use dailyWithData for "empty" check
  const chartData = daily;

  const appTypeData = stats
    ? (Array.isArray(stats.top_app_types)
        ? stats.top_app_types.map((t: { type: string; count: number }) => ({ name: t.type, value: t.count }))
        : Object.entries(stats.top_app_types as Record<string, number>).map(([name, value]) => ({ name, value }))
      )
    : [];

  // ── Fix: read avg_duration_seconds from top-level field (not nested) ─────────
  // Old API: stats.duration_seconds.average  → showed NaN
  // New API: stats.avg_duration_seconds      → correct number
  const avgDuration = stats
    ? (stats.avg_duration_seconds ?? (stats as { duration_seconds?: { average?: number } }).duration_seconds?.average ?? null)
    : null;

  const METRICS = stats
    ? [
        {
          icon:  <Layers size={18} />,
          value: stats.total_builds,
          label: 'Total Builds',
          color: 'var(--color-info)',
        },
        {
          icon:  <CheckCircle size={18} />,
          value: `${(stats.success_rate_percent ?? 0).toFixed(1)}%`,
          label: 'Success Rate',
          color: 'var(--color-success)',
        },
        {
          icon:  <Clock size={18} />,
          // Guard against null/undefined/NaN before calling Math.round
          value: avgDuration != null && !isNaN(avgDuration)
            ? `${Math.round(avgDuration)}s`
            : '—',
          label: 'Avg Duration',
          color: 'var(--color-warning)',
        },
        {
          icon:  <TrendingUp size={18} />,
          value: appTypeData.length,
          label: 'App Types Built',
          color: 'var(--color-accent-secondary)',
        },
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
        {/* Area — daily builds over time */}
        <div className="chart-card card chart-card--wide">
          <p className="chart-title">Daily Builds — Last {days} days</p>
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={chartData} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="gSuccess" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#22C55E" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#22C55E" stopOpacity={0}/>
                  </linearGradient>
                  <linearGradient id="gFailed" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#EF4444" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#EF4444" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid {...GRID_PROPS} />
                <XAxis
                  dataKey="date"
                  {...AXIS_PROPS}
                  tickFormatter={(v: string) => v.slice(5)} // show MM-DD only
                />
                <YAxis {...AXIS_PROPS} allowDecimals={false} />
                <Tooltip content={<ChartTooltip />} />
                <Legend wrapperStyle={{ fontSize: '0.75rem', paddingTop: '12px' }} />
                {/* dataKey="success" matches the renamed field in analytics.py */}
                <Area
                  type="monotone"
                  dataKey="success"
                  name="Success"
                  stroke="#22C55E"
                  fill="url(#gSuccess)"
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4 }}
                />
                <Area
                  type="monotone"
                  dataKey="failed"
                  name="Failed"
                  stroke="#EF4444"
                  fill="url(#gFailed)"
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="chart-empty">No data yet — run your first build!</div>
          )}
        </div>

        {/* Bar — success vs failed */}
        <div className="chart-card card">
          <p className="chart-title">Success vs Failed</p>
          {dailyWithData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={chartData} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                <CartesianGrid {...GRID_PROPS} />
                <XAxis
                  dataKey="date"
                  {...AXIS_PROPS}
                  tickFormatter={(v: string) => v.slice(5)}
                />
                <YAxis {...AXIS_PROPS} allowDecimals={false} />
                <Tooltip content={<ChartTooltip />} />
                <Legend wrapperStyle={{ fontSize: '0.75rem', paddingTop: '12px' }} />
                <Bar dataKey="success" name="Success" fill="#22C55E" radius={[4,4,0,0]} />
                <Bar dataKey="failed"  name="Failed"  fill="#EF4444" radius={[4,4,0,0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="chart-empty">No completed builds yet</div>
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
                  label={({ name, percent }) =>
                    percent && percent > 0.05
                      ? `${name} ${((percent ?? 0) * 100).toFixed(0)}%`
                      : ''
                  }
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
            <div className="chart-empty">No completed builds yet</div>
          )}
        </div>
      </div>
    </div>
  );
}
