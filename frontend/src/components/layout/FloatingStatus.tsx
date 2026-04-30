import { Activity } from 'lucide-react';
import { useHealth } from '../../hooks/useHealth';
import './FloatingStatus.css';

export function FloatingStatus() {
  const health = useHealth();
  const llmStatus = health?.llm?.status ?? 'unknown';
  const isHealthy = llmStatus === 'healthy';

  return (
    <div className="floating-status" role="status" aria-live="polite">
      <div className={`floating-status-dot ${isHealthy ? 'dot--healthy' : 'dot--degraded'}`} />
      <div className="floating-status-text">
        <span className="floating-status-title">
          {health ? 'Backend Online' : 'Connecting…'}
        </span>
        {health && (
          <span className="floating-status-sub">
            <Activity size={9} />
            LLM: {llmStatus} · {health.worker_pool?.active ?? 0} active
          </span>
        )}
      </div>
    </div>
  );
}
