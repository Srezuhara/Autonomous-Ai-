import { CheckCircle, XCircle, Clock, Play, AlertTriangle, MinusCircle } from 'lucide-react';

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
  running:   { icon: Play,        cls: 'badge-info',    label: 'Running'   },
  queued:    { icon: Clock,       cls: 'badge-warning', label: 'Queued'    },
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const config = STATUS_MAP[status] ?? { icon: Clock, cls: 'badge-neutral', label: status };
  const { icon: Icon, cls, label } = config;
  const isRunning = status === 'running';

  return (
    <span className={`badge ${cls}`}>
      <Icon size={11} className={isRunning ? 'spin-icon' : ''} />
      {label}
    </span>
  );
}
