import { useState } from 'react';
import { TrendingUp, CheckCircle, Clock, Layers, Zap } from 'lucide-react';
import { useStats, useDailyStats } from '../hooks/useQueries';
import { BuildTrendChart, StatusBreakdown, AppTypeChart } from '@/components/charts';
import type { DailyRow } from '@/components/charts';
import './Statistics.css';

// ── Token usage section ────────────────────────────────────────────────────────
function TokenStat({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
}) {
  return (
    <div className="token-stat-pill card">
      <div className="metric-label">{label}</div>
      <div className="metric-value" style={color ? { color } : undefined}>{value}</div>
      {sub && <div className="token-stat-sub">{sub}</div>}
    </div>
  );
}

function TokenUsageSection({
  stats,
  isLoading,
}: {
  stats: ReturnType<typeof useStats>['data'];
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div className="token-section">
        <div className="skeleton" style={{ height: 110 }} />
      </div>
    );
  }

  const usage = stats?.token_usage;

  const noData =
    !usage ||
    (usage.total_tokens === 0 && usage.avg_tokens_per_build === null);

  if (noData) {
    return (
      <div className="token-section card" style={{ padding: 'var(--space-5)' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-2)',
          marginBottom: 'var(--space-3)',
        }}>
          <Zap size={15} style={{ color: 'var(--color-warning)' }} />
          <span className="section-label">Token usage</span>
        </div>
        <p style={{
          fontSize: 'var(--text-sm)',
          color: 'var(--text-tertiary)',
          lineHeight: 'var(--leading-relaxed)',
        }}>
          No token data yet. Token tracking is recorded for builds run after
          Phase 17 was deployed. Complete a new build to see usage statistics.
        </p>
      </div>
    );
  }

  const fmt = (n: number) =>
    n >= 1_000_000
      ? `${(n / 1_000_000).toFixed(2)}M`
      : n >= 1_000
      ? `${(n / 1_000).toFixed(1)}K`
      : String(n);

  const totalCost =
    (usage.total_prompt_tokens     / 1_000_000) * 0.59 +
    (usage.total_completion_tokens / 1_000_000) * 0.79;

  const avgTokens = usage.avg_tokens_per_build ?? 0;
  const avgCost   = avgTokens > 0
    ? ((avgTokens * 0.35) / 1_000_000)   // blended ~$0.35/1M average
    : null;

  const inputPct = usage.total_tokens > 0
    ? Math.round((usage.total_prompt_tokens / usage.total_tokens) * 100)
    : 0;
  const outputPct = 100 - inputPct;

  return (
    <div className="token-section">
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-2)',
        marginBottom: 'var(--space-4)',
      }}>
        <Zap size={15} style={{ color: 'var(--color-warning)' }} />
        <span className="section-label">Token usage — all builds</span>
      </div>

      <div className="token-stats-grid">
        <TokenStat
          label="Total tokens"
          value={fmt(usage.total_tokens)}
          sub="across all builds"
          color="var(--color-accent-secondary)"
        />
        <TokenStat
          label="Prompt tokens"
          value={fmt(usage.total_prompt_tokens)}
          sub={`${inputPct}% of total`}
        />
        <TokenStat
          label="Completion tokens"
          value={fmt(usage.total_completion_tokens)}
          sub={`${outputPct}% of total`}
        />
        <TokenStat
          label="Avg per build"
          value={avgTokens > 0 ? fmt(avgTokens) : '—'}
          sub="tokens / build"
        />
        <TokenStat
          label="Est. total cost"
          value={totalCost < 0.001 ? '<$0.001' : `$${totalCost.toFixed(3)}`}
          sub="at listed token rates"
          color="var(--color-success)"
        />
        {avgCost !== null && (
          <TokenStat
            label="Est. cost / build"
            value={avgCost < 0.001 ? '<$0.001' : `$${avgCost.toFixed(3)}`}
            sub="blended rate"
            color="var(--color-success)"
          />
        )}
      </div>

      {/* Input vs output split bar */}
      <div style={{ marginTop: 'var(--space-4)' }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontSize: 'var(--text-xs)',
          color: 'var(--text-tertiary)',
          marginBottom: 'var(--space-2)',
        }}>
          <span>Prompt ({inputPct}%)</span>
          <span>Completion ({outputPct}%)</span>
        </div>
        <div style={{
          height: 6,
          borderRadius: 'var(--radius-full)',
          background: 'var(--color-bg-elevated)',
          overflow: 'hidden',
          display: 'flex',
        }}>
          <div style={{
            width: `${inputPct}%`,
            background: 'var(--color-accent-primary)',
            transition: 'width 0.6s ease',
          }} />
          <div style={{
            width: `${outputPct}%`,
            background: 'var(--color-accent-secondary)',
            transition: 'width 0.6s ease',
          }} />
        </div>
        <div style={{
          display: 'flex',
          gap: 'var(--space-4)',
          marginTop: 'var(--space-2)',
          fontSize: 'var(--text-xs)',
          color: 'var(--text-tertiary)',
        }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{
              width: 8, height: 8, borderRadius: 2,
              background: 'var(--color-accent-primary)',
              display: 'inline-block',
            }} />
            Input ($0.59 / 1M tokens)
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{
              width: 8, height: 8, borderRadius: 2,
              background: 'var(--color-accent-secondary)',
              display: 'inline-block',
            }} />
            Output ($0.79 / 1M tokens)
          </span>
        </div>
      </div>
    </div>
  );
}

export default function Statistics() {
  const [days, setDays] = useState(14);
  const { data: stats, isLoading: statsLoading } = useStats();
  const { data: dailyRaw, isLoading: dailyLoading } = useDailyStats(days);

  const isLoading = statsLoading || dailyLoading;

  const daily: object[] = Array.isArray(dailyRaw)
    ? dailyRaw
    : (dailyRaw as { data?: object[] } | null)?.data ?? [];

  const chartData = daily;

  const appTypeData = stats
    ? (Array.isArray(stats.top_app_types)
        ? stats.top_app_types.map((t: { type: string; count: number }) => ({ name: t.type, value: t.count }))
        : Object.entries(stats.top_app_types as Record<string, number>).map(([name, value]) => ({ name, value }))
      )
    : [];

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

      {/* Charts. Forms were chosen before colour: a trend area for
          change-over-time, a part-to-whole bar for outcome mix, and horizontal
          bars for magnitude comparison. See components/charts. */}
      <div className="charts-grid">
        <BuildTrendChart data={chartData as DailyRow[]} days={days} />
        <StatusBreakdown byStatus={(stats?.by_status ?? {}) as Record<string, number>} />
        <AppTypeChart data={appTypeData} />
      </div>

      {/* ── Phase 17: Token usage section ── */}
      <TokenUsageSection stats={stats} isLoading={statsLoading} />
    </div>
  );
}
