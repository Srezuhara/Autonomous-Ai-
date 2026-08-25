import { CheckCircle, XCircle, Clock, Loader, AlertTriangle, MinusCircle } from 'lucide-react';

interface StatusBadgeProps {
  status: string;
}

const STATUS_MAP: Record<string, { icon: typeof Clock; cls: string; label: string }> = {
  done:      { icon: CheckCircle, cls: 'badge-success', label: 'Done'      },
  // Phase 21: completed but degraded — usable code plus a handoff document.
  // Warning styling, not error: the build succeeded enough to download.
  done_with_context: {
    icon: AlertTriangle, cls: 'badge-warning', label: 'Done (with context)',
  },
  failed:    { icon: XCircle,     cls: 'badge-error',   label: 'Failed'    },
  // Neutral, not error. A user-stopped build did not fail, and status colour is
  // reserved vocabulary — spending "critical" red on it both overstates the
  // outcome and disagrees with the charts, where cancelled is achromatic.
  cancelled: { icon: MinusCircle, cls: 'badge-neutral', label: 'Cancelled' },
  // Violet, not blue. The validated chart palette dropped blue entirely — it
  // scored 0.7 deltaE against the brand violet under deuteranopia — so a blue
  // "running" badge sitting beside a violet "running" chart segment told two
  // different stories about the same state.
  running:   { icon: Loader,      cls: 'badge-accent',  label: 'Running'   },
  queued:    { icon: Clock,       cls: 'badge-warning', label: 'Queued'    },
  // The backend emits `pending` for a build that exists but has not been
  // picked up yet. It had no mapping, so it fell through to the default and
  // rendered as a raw lowercase chip reading "pending" — the only badge in the
  // product that was not a designed one.
  pending:   { icon: Clock,       cls: 'badge-neutral', label: 'Pending'   },
};

/**
 * The running badge used to spin its icon on an infinite loop — and the icon
 * was a Play triangle, so it read as a rotating triangle rather than as
 * progress. On the dashboard that meant one loop per running build in the
 * list. The glyph is now a loader (the right shape for indeterminate work) and
 * it holds still: a badge reports state, and the one place live work should
 * actually animate is the active step marker on BuildProgress.
 */
export function StatusBadge({ status }: StatusBadgeProps) {
  const config = STATUS_MAP[status] ?? { icon: Clock, cls: 'badge-neutral', label: status };
  const { icon: Icon, cls, label } = config;

  return (
    <span className={`badge ${cls}`}>
      <Icon size={11} />
      {label}
    </span>
  );
}
