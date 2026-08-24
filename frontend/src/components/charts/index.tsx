/**
 * components/charts — dashboard data visualisation
 * =================================================
 * Recharts, styled to a validated dark palette. Form was chosen before colour:
 *
 *   build trend      → columns, ONE hue (sparse discrete daily counts)
 *   status breakdown → horizontal stacked bar (part-to-whole, reserved
 *                      status colours — not categorical)
 *   app types        → horizontal bars (compare magnitude; a pie cannot be
 *                      read for comparison, and the previous pie also rendered
 *                      invisibly)
 *   token split      → meter, not a two-slice pie
 *
 * Rules applied throughout:
 *   - text wears text tokens, never the series colour
 *   - grid and axes are recessive
 *   - 2px surface gaps between stacked segments so they read as separate marks
 *   - every chart has a real empty state; a flat line at zero is not data
 *   - a legend whenever there are 2+ series, with direct value labels
 */
import type { ReactNode } from 'react';
import {
  ResponsiveContainer, XAxis, YAxis, CartesianGrid,
  Tooltip, BarChart, Bar, LabelList,
} from 'recharts';
import './charts.css';

/* ── Shared furniture ─────────────────────────────────────────────────────── */

const AXIS = {
  stroke: 'var(--viz-axis)',
  tick: { fill: 'var(--viz-axis)', fontSize: 10, fontFamily: 'var(--font-mono)' },
  tickLine: false,
  axisLine: false,
} as const;

const GRID = {
  stroke: 'var(--viz-grid)',
  strokeDasharray: '0',
  vertical: false,
} as const;

interface TipRow { name: string; value: number | string; color?: string }

function Tip({ title, rows }: { title: string; rows: TipRow[] }) {
  return (
    <div className="viz-tip">
      <p className="viz-tip__title">{title}</p>
      {rows.map((r) => (
        <p className="viz-tip__row" key={r.name}>
          {r.color && <span className="viz-tip__swatch" style={{ background: r.color }} />}
          <span className="viz-tip__name">{r.name}</span>
          <span className="viz-tip__value">{r.value}</span>
        </p>
      ))}
    </div>
  );
}

/** Card shell: title, optional action, and a guaranteed empty state. */
export function ChartFrame({
  title, hint, children, empty, emptyLabel = 'No data yet', className = '', action,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
  empty?: boolean;
  emptyLabel?: string;
  className?: string;
  action?: ReactNode;
}) {
  return (
    <section className={`viz-card ${className}`}>
      <header className="viz-card__head">
        <div>
          <h3 className="viz-card__title">{title}</h3>
          {hint && <p className="viz-card__hint">{hint}</p>}
        </div>
        {action}
      </header>
      {empty ? <div className="viz-empty">{emptyLabel}</div> : children}
    </section>
  );
}

/* ── 1. Build trend ───────────────────────────────────────────────────────── */

export interface DailyRow {
  date: string;
  total?: number;
  success?: number;
  failed?: number;
}

/**
 * Single-series daily volume. The old version drew two overlapping gradient
 * areas (success + failed) which, on a mostly-zero series, produced two flat
 * lines pinned to the axis and read as a broken chart.
 *
 * When every day is zero we say so instead of drawing that flat line.
 */
export function BuildTrendChart({ data, days }: { data: DailyRow[]; days: number }) {
  const hasAny = data.some((d) => (d.total ?? 0) > 0);
  const shaped = data.map((d) => ({
    ...d,
    label: d.date?.slice(5) ?? '',
  }));

  return (
    <ChartFrame
      title={`Build volume — last ${days} days`}
      hint={hasAny ? undefined : 'No builds recorded in this window'}
      empty={!hasAny}
      emptyLabel="No builds in this period — the range control above changes the window"
      className="viz-card--wide"
    >
      {/* Columns, not an area. Daily build counts are sparse discrete events —
          with one active day in fourteen, an area collapses to a flat line on
          the axis with an invisible one-unit blip. A column for that day is
          unmissable and does not imply a continuous quantity between days. */}
      <ResponsiveContainer width="100%" height={230}>
        <BarChart data={shaped} margin={{ top: 10, right: 8, left: -22, bottom: 0 }}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="label" {...AXIS} interval="preserveStartEnd" minTickGap={18} />
          <YAxis {...AXIS} allowDecimals={false} width={40} />
          <Tooltip
            cursor={{ fill: 'rgba(255,255,255,0.035)' }}
            content={({ active, payload, label }) =>
              active && payload?.length ? (
                <Tip
                  title={String(label)}
                  rows={[{ name: 'Builds', value: payload[0].value as number, color: 'var(--viz-seq)' }]}
                />
              ) : null
            }
          />
          {/* No entry animation. Recharts grows bars from zero height over
              ~1.5s; on a dashboard that is decorative motion on a surface the
              user hits constantly, and it leaves the chart empty-looking until
              it settles. Rendering final-state immediately is both faster and
              the correct restraint for this surface. */}
          <Bar
            dataKey="total"
            name="Builds"
            fill="var(--viz-seq)"
            radius={[4, 4, 0, 0]}
            maxBarSize={26}
            isAnimationActive={false}
          />
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

/* ── 2. Status breakdown ──────────────────────────────────────────────────── */

const STATUS_META: Record<string, { label: string; color: string }> = {
  done:              { label: 'Done',      color: 'var(--viz-done)' },
  done_with_context: { label: 'Degraded',  color: 'var(--viz-degraded)' },
  running:           { label: 'Running',   color: 'var(--viz-running)' },
  failed:            { label: 'Failed',    color: 'var(--viz-failed)' },
  cancelled:         { label: 'Cancelled', color: 'var(--viz-cancelled)' },
};

const STATUS_ORDER = ['done', 'done_with_context', 'running', 'cancelled', 'failed'];

/**
 * Part-to-whole across build outcomes. This replaced a chart labelled
 * "Success vs Failed" that actually re-plotted the same daily series as the
 * trend chart above it — two charts answering one question, and neither
 * showing the outcome mix that `by_status` already provides.
 */
export function StatusBreakdown({ byStatus }: { byStatus: Record<string, number> }) {
  const entries = STATUS_ORDER
    .filter((k) => (byStatus?.[k] ?? 0) > 0)
    .map((k) => ({ key: k, value: byStatus[k], ...STATUS_META[k] }));

  const total = entries.reduce((s, e) => s + e.value, 0);

  return (
    <ChartFrame
      title="Build outcomes"
      hint={total ? `${total} builds total` : undefined}
      empty={!total}
      emptyLabel="No builds recorded yet"
    >
      <div className="viz-stack">
        <div className="viz-stack__bar" role="img" aria-label="Build outcome distribution">
          {entries.map((e) => (
            <span
              key={e.key}
              className="viz-stack__seg"
              style={{
                width: `${(e.value / total) * 100}%`,
                background: e.color,
              }}
              title={`${e.label}: ${e.value}`}
            />
          ))}
        </div>

        {/* Legend doubles as the value table — identity is never colour-alone. */}
        <ul className="viz-legend">
          {entries.map((e) => (
            <li className="viz-legend__item" key={e.key}>
              <span className="viz-legend__swatch" style={{ background: e.color }} />
              <span className="viz-legend__label">{e.label}</span>
              <span className="viz-legend__value">{e.value}</span>
              <span className="viz-legend__pct">
                {((e.value / total) * 100).toFixed(0)}%
              </span>
            </li>
          ))}
        </ul>
      </div>
    </ChartFrame>
  );
}

/* ── 3. App types ─────────────────────────────────────────────────────────── */

export interface AppTypeRow { name: string; value: number }

/**
 * Horizontal bars, sorted, single hue. Length carries the magnitude, so colour
 * does not need to vary — a per-slice rainbow would imply these categories have
 * fixed identities that matter, which they do not.
 */
export function AppTypeChart({ data }: { data: AppTypeRow[] }) {
  const sorted = [...data].sort((a, b) => b.value - a.value).slice(0, 6);
  const height = Math.max(160, sorted.length * 46);

  return (
    <ChartFrame
      title="App types built"
      hint={sorted.length ? `${sorted.length} distinct types` : undefined}
      empty={sorted.length === 0}
      emptyLabel="No completed builds yet"
    >
      <ResponsiveContainer width="100%" height={height}>
        <BarChart
          data={sorted}
          layout="vertical"
          margin={{ top: 4, right: 34, left: 4, bottom: 4 }}
          barCategoryGap={10}
        >
          <CartesianGrid stroke="var(--viz-grid)" horizontal={false} />
          {/* In layout="vertical" the number axis must be bound explicitly.
              Without dataKey + domain, Recharts derived a domain from the wrong
              field and drew every bar ~3px wide regardless of its value. */}
          <XAxis type="number" dataKey="value" domain={[0, 'dataMax']} hide />
          <YAxis
            type="category"
            dataKey="name"
            width={104}
            {...AXIS}
            tick={{ fill: 'var(--text-secondary)', fontSize: 11, fontFamily: 'var(--font-sans)' }}
          />
          <Tooltip
            cursor={{ fill: 'rgba(255,255,255,0.03)' }}
            content={({ active, payload }) =>
              active && payload?.length ? (
                <Tip
                  title={String(payload[0].payload.name)}
                  rows={[{ name: 'Builds', value: payload[0].value as number, color: 'var(--viz-seq)' }]}
                />
              ) : null
            }
          />
          {/* fill lives on the Bar, not per-Cell: one hue for every category,
              because bar length already encodes the magnitude. */}
          <Bar
            dataKey="value"
            fill="var(--viz-seq)"
            radius={[0, 4, 4, 0]}
            maxBarSize={18}
            isAnimationActive={false}
          >
            {/* Direct labels — no need to read back to an axis. */}
            <LabelList
              dataKey="value"
              position="right"
              offset={10}
              className="viz-barlabel"
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
