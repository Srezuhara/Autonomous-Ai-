import { CheckCircle, XCircle, Clock, Play } from 'lucide-react';

interface StatusBadgeProps {
  status: string;
}

const STATUS_MAP: Record<string, { icon: typeof Clock; cls: string; label: string }> = {
  done:      { icon: CheckCircle, cls: 'badge-success', label: 'Done'      },
  failed:    { icon: XCircle,     cls: 'badge-error',   label: 'Failed'    },
  cancelled: { icon: XCircle,     cls: 'badge-error',   label: 'Cancelled' },
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
