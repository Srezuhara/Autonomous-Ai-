import { useState } from 'react';
import { Link } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import {
  RefreshCw, LayoutGrid, Activity, CheckCircle2, Timer, Boxes, PlugZap,
} from 'lucide-react';
import { useBuilds, useStats } from '../hooks/useQueries';
import { BuildCard } from '../components/shared/BuildCard';
import { StatTile } from '../components/shared/StatTile';
import { appItem, appStagger, popIn, CHIP_ID, layoutSpring } from '../lib/motion';
import './Dashboard.css';

/**
 * Dashboard — the build index.
 *
 * Rebuilt on app-shell.css. The old screen carried its own header markup, its
 * own `MetricCard`, and the legacy `.tab-group` (whose `.tab` rule animates
 * `transition: all`). All three are gone: the header is `.page-head`, the KPI
 * row is the shared `StatTile`, and filters are `.chip[aria-pressed]`.
 *
 * The "New Build" button was dropped from the header — the sidebar pins that
 * action on every screen, so a second copy here was just competing with it.
 *
 * ── Motion ────────────────────────────────────────────────────────────────
 * This screen's motion exists to answer one question: *what changed when I
 * clicked that filter?* Three pieces do it together:
 *
 *   1. The pressed chip's tint is a single shared element that slides between
 *      chips, so the eye follows the selection instead of re-finding it.
 *   2. Surviving rows keep their identity and slide (`layout` on BuildCard);
 *      rows that no longer match fade out.
 *   3. The list is keyed on the filter so a genuinely different result set
 *      re-runs the stagger rather than silently swapping underneath.
 *
 * The KPI row animates on mount only. It re-renders on every stats poll and a
 * row that re-cascaded each time would be a metronome in the corner of the eye.
 */

// Phase 21: 'Partial' surfaces done_with_context builds — completed but
// degraded or quota-paused. They are downloadable, so they get their own
// filter rather than being lumped in with failures.
//
// `queued` and `cancelled` were missing entirely: a build in either state was
// reachable from "All" but from no filter of its own.
const STATUS_FILTERS = [
  { value: 'all',               label: 'All'       },
  { value: 'running',           label: 'Running'   },
  { value: 'queued',            label: 'Queued'    },
  { value: 'done',              label: 'Done'      },
  { value: 'done_with_context', label: 'Partial'   },
  { value: 'failed',            label: 'Failed'    },
  { value: 'cancelled',         label: 'Cancelled' },
] as const;

export default function Dashboard() {
  const [filter, setFilter] = useState<string>('all');
  const { data, isLoading, isError, refetch, isFetching } = useBuilds(
    filter === 'all' ? undefined : filter
  );
  const { data: stats } = useStats();

  // ── avg_duration_seconds is the top-level field ───────────────────────────
  // The nested `duration_seconds.average` is kept as a fallback for older
  // backends; reading only the nested one used to yield Math.round(undefined).
  const avgDuration: number | null = stats
    ? (stats.avg_duration_seconds ?? stats.duration_seconds?.average ?? null)
    : null;

  const hasAvgDuration = avgDuration != null && !isNaN(avgDuration);
  const topType = stats?.top_app_types?.[0]?.type ?? '—';

  // The envelope's `total` is the count of matching builds; `projects.length`
  // is only ever the current page of 50, so it under-reported past that.
  const total = data?.total ?? 0;

  return (
    <div className="dashboard page-wrapper">

      <header className="page-head">
        <div className="page-head__text">
          <span className="page-head__kicker">
            <LayoutGrid size={11} strokeWidth={2} />
            Build index
          </span>
          <h1 className="page-head__title">
            Everything you have <em>shipped</em>
          </h1>
          <p className="page-head__sub">
            Every run the pipeline has taken, with its review scores and the
            reason it ended. Open one for the full report.
          </p>
        </div>
        <div className="page-head__aside">
          <button
            className="btn btn-ghost btn-icon"
            onClick={() => refetch()}
            disabled={isFetching}
            aria-label="Refresh builds"
          >
            <RefreshCw size={16} className={isFetching ? 'spin-icon' : ''} />
          </button>
        </div>
      </header>

      {stats && (
        <motion.div
          className="dash-metrics"
          variants={appStagger()}
          initial="hidden"
          animate="visible"
        >
          <StatTile
            label="Total builds"
            value={stats.total_builds}
            icon={<Activity size={14} strokeWidth={2} />}
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
            label="Top app type"
            value={topType}
            icon={<Boxes size={14} strokeWidth={2} />}
          />
        </motion.div>
      )}

      <section className="dash-body">
        <div className="dash-controls">
          <div className="dash-filters" role="group" aria-label="Filter builds by status">
            {STATUS_FILTERS.map(f => {
              const active = filter === f.value;
              return (
                <button
                  key={f.value}
                  type="button"
                  className="chip chip--shared"
                  aria-pressed={active}
                  onClick={() => setFilter(f.value)}
                >
                  {/* One element shared across seven buttons. Framer keeps a
                      single DOM node and animates it between the two positions
                      whenever the `layoutId` moves, which is why the tint
                      travels instead of cross-fading. It is `aria-hidden` and
                      sits behind the label — the pressed state is still carried
                      by `aria-pressed`, which is what assistive tech reads. */}
                  {active && (
                    <motion.span
                      layoutId={CHIP_ID}
                      className="chip__active"
                      transition={layoutSpring}
                      aria-hidden
                    />
                  )}
                  <span className="chip__label">{f.label}</span>
                </button>
              );
            })}
          </div>
          {/* Keyed on the number so a changed count animates in place. Without
              the key React reuses the node and the digits swap silently — the
              one piece of feedback confirming the filter actually did something
              when the list below is already empty. */}
          {data && !isError && (
            <AnimatePresence mode="wait" initial={false}>
              <motion.span
                key={total}
                className="dash-count figure figure--sm"
                variants={popIn}
                initial="hidden"
                animate="visible"
                exit="exit"
              >
                {total} build{total !== 1 ? 's' : ''}
              </motion.span>
            </AnimatePresence>
          )}
        </div>

        <div className="dash-list">
          {/*
            One AnimatePresence over all four mutually exclusive list states —
            loading, error, empty, results. Separate ones would let the old
            state's exit and the new state's enter overlap and stack two full
            panels on top of each other; `mode="wait"` across a single presence
            makes the swap sequential and keeps the column one panel tall.
          */}
          <AnimatePresence mode="wait" initial={false}>
          {isLoading && (
            <motion.div
              key="loading"
              className="dash-skeletons"
              aria-busy
              aria-label="Loading builds"
              variants={appStagger(0.05)}
              initial="hidden"
              animate="visible"
              exit="exit"
            >
              {Array.from({ length: 4 }, (_, i) => (
                <motion.div key={i} className="panel dash-skeleton" variants={appItem} />
              ))}
            </motion.div>
          )}

          {/* `role="alert"` because this appears asynchronously, after a fetch
              fails. Without it a screen-reader user is left on a list that
              simply never populates, with nothing announced. */}
          {isError && (
            <motion.div
              key="error"
              className="panel panel--pad-lg empty"
              role="alert"
              variants={appItem}
              initial="hidden"
              animate="visible"
              exit="exit"
            >
              <PlugZap size={22} strokeWidth={1.5} className="empty__icon" />
              <h3 className="empty__title">Backend unreachable</h3>
              <p className="empty__body">
                Nothing is answering on the API. Start the server with{' '}
                <code className="dash-code">python start_server.py</code>{' '}
                and try again.
              </p>
              <button className="btn btn-secondary" onClick={() => refetch()}>
                Retry
              </button>
            </motion.div>
          )}

          {!isLoading && !isError && data?.projects.length === 0 && (
            <motion.div
              key="empty"
              className="panel panel--pad-lg empty"
              variants={appItem}
              initial="hidden"
              animate="visible"
              exit="exit"
            >
              <Boxes size={22} strokeWidth={1.5} className="empty__icon" />
              <h3 className="empty__title">
                {filter === 'all' ? 'No builds yet' : 'Nothing in this state'}
              </h3>
              <p className="empty__body">
                {filter === 'all'
                  ? 'Describe an app in plain English and the pipeline takes it from there.'
                  : 'No build currently matches this filter. Try another, or view all builds.'}
              </p>
              {filter === 'all'
                ? <Link to="/build" className="btn btn-primary">Start a build</Link>
                : (
                  <button className="btn btn-secondary" onClick={() => setFilter('all')}>
                    View all builds
                  </button>
                )}
            </motion.div>
          )}

          {/* Keyed on the filter, not on the data: a poll returning the same
              rows must not restart the cascade, but switching filters is a
              genuinely different list and should read as one. Rows themselves
              carry `layout`, so any row present in both lists slides between
              its old and new position rather than being replaced. */}
          {!isLoading && !isError && !!data?.projects.length && (
            <motion.div
              key={`list-${filter}`}
              className="dash-results"
              variants={appStagger(0.028)}
              initial="hidden"
              animate="visible"
              exit="exit"
            >
              {data.projects.map(project => (
                <BuildCard key={project.build_id} project={project} />
              ))}
            </motion.div>
          )}
          </AnimatePresence>
        </div>
      </section>
    </div>
  );
}
