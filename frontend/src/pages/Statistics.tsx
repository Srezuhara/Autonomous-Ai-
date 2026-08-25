import { useState } from 'react';
import { motion } from 'framer-motion';
import { BarChart3, CheckCircle2, Timer, Layers, Star, Zap } from 'lucide-react';
import { useStats, useDailyStats } from '../hooks/useQueries';
import { BuildTrendChart, StatusBreakdown, AppTypeChart } from '@/components/charts';
import type { DailyRow } from '@/components/charts';
import { StatTile } from '../components/shared/StatTile';
import {
  RATE_INPUT_PER_M, RATE_OUTPUT_PER_M,
  formatTokens, formatCost, costOf, blendedCostOf, rateLabel,
} from '../lib/pricing';
import { appItem, appStagger, CHIP_ID, layoutSpring, EASE, DURATION } from '../lib/motion';
import './Statistics.css';

/**
 * Statistics — platform-wide analytics.
 *
 * The charts were converted to the design system first and the rest of the page
 * was left behind: a local header, a local metric card, and a token section
 * carrying 19 inline `style={{}}` blocks including its own split bar. That is
 * all gone — the header is `.page-head`, the KPI row is the shared `StatTile`,
 * the range picker is `.chip[aria-pressed]`, and the split bar is `.meter`.
 *
 * `builds_today`, `builds_this_week` and `average_review_score` are surfaced
 * here for the first time; the API has always returned them and nothing
 * rendered them.
 *
 * ── Motion ────────────────────────────────────────────────────────────────
 * The range picker uses the same travelling chip as the dashboard filter, from
 * the same `layoutId` vocabulary — two screens, one selection behaviour. The
 * KPI row and the charts cascade once on mount, in reading order, and the
 * token split bar grows from zero so the ratio is read as a proportion rather
 * than found already drawn.
 *
 * Charts are left entirely alone. Recharts runs its own entry animation on its
 * series, and layering a container reveal on top of it produces two curves
 * fighting over the same pixels.
 */

const RANGES = [7, 14, 30] as const;

// ── Token usage ───────────────────────────────────────────────────────────────

function TokenUsage({ stats, isLoading }: {
  stats: ReturnType<typeof useStats>['data'];
  isLoading: boolean;
}) {
  if (isLoading) {
    return <div className="panel stats-skeleton stats-skeleton--tokens" aria-busy />;
  }

  const usage = stats?.token_usage;
  const noData = !usage || (usage.total_tokens === 0 && usage.avg_tokens_per_build === null);

  if (noData) {
    return (
      <section className="panel panel--pad stats-tokens">
        <header className="stats-tokens__head">
          <Zap size={13} className="stats-tokens__icon" aria-hidden />
          <span className="ulabel">Token usage</span>
        </header>
        <p className="stats-empty">
          No token data yet. Usage is recorded for builds run after Phase 17 was
          deployed — complete a new build to see it here.
        </p>
      </section>
    );
  }

  const totalCost = costOf(usage.total_prompt_tokens, usage.total_completion_tokens);
  const avgTokens = usage.avg_tokens_per_build ?? 0;
  const avgCost   = avgTokens > 0 ? blendedCostOf(avgTokens) : null;

  const inputPct = usage.total_tokens > 0
    ? Math.round((usage.total_prompt_tokens / usage.total_tokens) * 100)
    : 0;
  const outputPct = 100 - inputPct;

  return (
    <section className="panel panel--pad stats-tokens">
      <header className="stats-tokens__head">
        <Zap size={13} className="stats-tokens__icon" aria-hidden />
        <span className="ulabel">Token usage — all builds</span>
      </header>

      {/* A plain definition row, not six more bordered tiles. The KPI row above
          is the page's tile row; repeating the shape here flattened the two
          into one undifferentiated field of boxes. */}
      <dl className="stats-tokens__grid">
        <TokenFigure label="Total"        value={formatTokens(usage.total_tokens)} />
        <TokenFigure label="Prompt"       value={formatTokens(usage.total_prompt_tokens)} hint={`${inputPct}% of total`} />
        <TokenFigure label="Completion"   value={formatTokens(usage.total_completion_tokens)} hint={`${outputPct}% of total`} />
        <TokenFigure label="Avg / build"  value={avgTokens > 0 ? formatTokens(avgTokens) : '—'} />
        <TokenFigure label="Est. cost"    value={formatCost(totalCost)} hint="at listed rates" />
        {avgCost !== null && (
          <TokenFigure label="Cost / build" value={formatCost(avgCost)} hint="blended rate" />
        )}
      </dl>

      {/* Input vs output split — the shared meter, not a bespoke flex bar. */}
      <div className="stats-split">
        <div
          className="meter meter--split stats-split__bar"
          role="img"
          aria-label={`Prompt ${inputPct} percent, completion ${outputPct} percent of all tokens`}
        >
          {/* Grown from zero rather than drawn at value. The bar's whole job
              is to say "this much of your spend is prompt" — a proportion is
              read far more reliably when you watch it being laid down. Width,
              not scaleX, because the two halves have to displace each other
              inside a flex row; a transform would let them overlap. */}
          <motion.div
            className="meter__fill"
            initial={{ width: 0 }}
            animate={{ width: `${inputPct}%` }}
            transition={{ duration: DURATION.slow, ease: EASE.out }}
          />
          <motion.div
            className="meter__fill meter__fill--alt"
            initial={{ width: 0 }}
            animate={{ width: `${outputPct}%` }}
            transition={{ duration: DURATION.slow, ease: EASE.out, delay: 0.06 }}
          />
        </div>

        <div className="stats-split__legend">
          <span className="stats-split__key">
            <span className="stats-split__swatch" aria-hidden />
            Prompt {inputPct}% · {rateLabel(RATE_INPUT_PER_M)}
          </span>
          <span className="stats-split__key">
            <span className="stats-split__swatch stats-split__swatch--alt" aria-hidden />
            Completion {outputPct}% · {rateLabel(RATE_OUTPUT_PER_M)}
          </span>
        </div>
      </div>
    </section>
  );
}

function TokenFigure({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="stats-tokens__item">
      <dt className="ulabel">{label}</dt>
      <dd className="figure figure--md">{value}</dd>
      {hint && <dd className="stats-tokens__hint">{hint}</dd>}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Statistics() {
  const [days, setDays] = useState<number>(14);
  const { data: stats, isLoading: statsLoading } = useStats();
  const { data: dailyRaw, isLoading: dailyLoading } = useDailyStats(days);

  const isLoading = statsLoading || dailyLoading;

  const daily: object[] = Array.isArray(dailyRaw)
    ? dailyRaw
    : (dailyRaw as { data?: object[] } | null)?.data ?? [];

  const appTypeData = (stats?.top_app_types ?? []).map(t => ({ name: t.type, value: t.count }));

  const avgDuration = stats
    ? (stats.avg_duration_seconds ?? stats.duration_seconds?.average ?? null)
    : null;
  const hasAvgDuration = avgDuration != null && !isNaN(avgDuration);

  const avgReview = stats?.average_review_score;
  const hasAvgReview = avgReview != null && !isNaN(avgReview);

  return (
    <div className="statistics page-wrapper">

      <header className="page-head">
        <div className="page-head__text">
          <span className="page-head__kicker">
            <BarChart3 size={11} strokeWidth={2} />
            Platform analytics
          </span>
          <h1 className="page-head__title">
            How the pipeline is <em>performing</em>
          </h1>
          <p className="page-head__sub">
            Throughput, outcome mix and token spend across every build this
            instance has run.
          </p>
        </div>
        <div className="page-head__aside">
          <div className="stats-ranges" role="group" aria-label="Trend range">
            {RANGES.map(d => {
              const active = days === d;
              return (
                <button
                  key={d}
                  type="button"
                  className="chip chip--shared"
                  aria-pressed={active}
                  onClick={() => setDays(d)}
                >
                  {/* Same `layoutId` constant as the dashboard filters. Only
                      one chip row is ever mounted at a time, so the shared id
                      cannot collide between the two screens. */}
                  {active && (
                    <motion.span
                      layoutId={CHIP_ID}
                      className="chip__active"
                      transition={layoutSpring}
                      aria-hidden
                    />
                  )}
                  <span className="chip__label">{d}d</span>
                </button>
              );
            })}
          </div>
        </div>
      </header>

      {isLoading ? (
        <motion.div
          className="stats-metrics"
          variants={appStagger(0.05)}
          initial="hidden"
          animate="visible"
        >
          {Array.from({ length: 4 }, (_, i) => (
            <motion.div key={i} className="panel stats-skeleton" aria-busy variants={appItem} />
          ))}
        </motion.div>
      ) : stats && (
        <motion.div
          className="stats-metrics"
          variants={appStagger()}
          initial="hidden"
          animate="visible"
        >
          <StatTile
            label="Total builds"
            value={stats.total_builds}
            icon={<Layers size={14} strokeWidth={2} />}
            hint={`${stats.builds_today} today · ${stats.builds_this_week} this week`}
          />
          <StatTile
            label="Success rate"
            value={(stats.success_rate_percent ?? 0).toFixed(1)}
            unit="%"
            icon={<CheckCircle2 size={14} strokeWidth={2} />}
          />
          <StatTile
            label="Avg duration"
            value={hasAvgDuration ? Math.round(avgDuration) : '—'}
            unit={hasAvgDuration ? 's' : undefined}
            icon={<Timer size={14} strokeWidth={2} />}
          />
          <StatTile
            label="Avg review"
            value={hasAvgReview ? avgReview.toFixed(1) : '—'}
            unit={hasAvgReview ? '/ 10' : undefined}
            icon={<Star size={14} strokeWidth={2} />}
          />
        </motion.div>
      )}

      {/* Charts. Forms were chosen before colour: a trend area for
          change-over-time, a part-to-whole bar for outcome mix, and horizontal
          bars for magnitude comparison. See components/charts. */}
      {/* The three chart panels cascade; the charts inside them do not get an
          extra wrapper, so Recharts' own series animation is untouched. */}
      <motion.div
        className="charts-grid"
        variants={appStagger(0.06, 0.05)}
        initial="hidden"
        animate="visible"
      >
        {/* The trend chart is the grid's full-bleed row. The span has to live
            on this wrapper, because the wrapper is now the grid item — the
            `viz-frame--wide` rule on the panel inside it resolves against this
            box, not against `.charts-grid`, and would silently do nothing. */}
        <motion.div variants={appItem} className="charts-grid__cell charts-grid__cell--wide">
          <BuildTrendChart data={daily as DailyRow[]} days={days} />
        </motion.div>
        <motion.div variants={appItem} className="charts-grid__cell">
          <StatusBreakdown byStatus={(stats?.by_status ?? {}) as Record<string, number>} />
        </motion.div>
        <motion.div variants={appItem} className="charts-grid__cell">
          <AppTypeChart data={appTypeData} />
        </motion.div>
      </motion.div>

      <TokenUsage stats={stats} isLoading={statsLoading} />
    </div>
  );
}
