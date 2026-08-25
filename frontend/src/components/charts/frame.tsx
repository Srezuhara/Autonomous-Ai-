/**
 * components/charts/frame — the chart furniture that needs no charting library
 * ============================================================================
 * `ChartFrame` and `StatusBreakdown` are pure DOM and CSS: a panel with a
 * guaranteed empty state, and a part-to-whole meter built from `.meter--split`
 * plus a legend table.
 *
 * They live here rather than in `charts/index.tsx` for one reason: that module
 * imports Recharts at the top level, so importing *anything* from it drags the
 * whole library into the importing chunk. Statistics is lazy and can afford
 * that; Landing sits in the entry chunk and cannot — it would add ~100 kB gzip
 * to the marketing page for a bar made of two divs.
 *
 * `charts/index.tsx` re-exports both names, so existing imports are unchanged.
 */
import type { ReactNode } from 'react';
import './charts.css';

/**
 * Frame: title, optional action, and a guaranteed empty state.
 *
 * On `.panel` like every other surface in the app. It used to be `.viz-card`,
 * a third card style whose only difference from `.panel` was `--radius-xl`
 * instead of `--radius-lg` — visible as a mismatched corner wherever a chart
 * sat beside a panel, which on Statistics is everywhere.
 */
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
    <section className={`panel panel--pad viz-frame ${className}`.trim()}>
      <header className="viz-frame__head">
        <div>
          <h3 className="viz-frame__title">{title}</h3>
          {hint && <p className="viz-frame__hint">{hint}</p>}
        </div>
        {action}
      </header>
      {empty
        ? <div className="empty empty--inset"><p className="empty__body">{emptyLabel}</p></div>
        : children}
    </section>
  );
}

/* ── Status breakdown ─────────────────────────────────────────────────────── */

const STATUS_META: Record<string, { label: string; color: string }> = {
  done:              { label: 'Done',      color: 'var(--viz-done)' },
  done_with_context: { label: 'Degraded',  color: 'var(--viz-degraded)' },
  running:           { label: 'Running',   color: 'var(--viz-running)' },
  failed:            { label: 'Failed',    color: 'var(--viz-failed)' },
  cancelled:         { label: 'Cancelled', color: 'var(--viz-cancelled)' },
  // `queued` and `pending` were absent from both maps, so builds in either
  // state were excluded from the total while the frame's hint still read
  // "N builds total" from a different count — every percentage below was
  // computed against the wrong denominator. Both are pre-work states, so they
  // share the achromatic treatment `cancelled` uses.
  queued:            { label: 'Queued',    color: 'var(--viz-cancelled)' },
  pending:           { label: 'Pending',   color: 'var(--viz-cancelled)' },
};

/* Pipeline order: not yet started → in flight → outcomes. */
const STATUS_ORDER = [
  'done', 'done_with_context', 'running', 'queued', 'pending', 'cancelled', 'failed',
];

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
      /* `total` is the sum of the segments actually drawn, so the label and
         the percentages below it always agree. */
      empty={!total}
      emptyLabel="No builds recorded yet"
    >
      <div className="viz-stack">
        <div
          className="meter meter--split viz-stack__bar"
          role="img"
          aria-label="Build outcome distribution"
        >
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
