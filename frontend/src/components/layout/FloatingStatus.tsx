import { useState } from 'react';
import { Activity, KeyRound, RotateCcw } from 'lucide-react';
import { useHealth } from '../../hooks/useHealth';
import { api } from '../../api/client';
import './FloatingStatus.css';

export function FloatingStatus() {
  const { health, refetch } = useHealth();
  const [isResetting, setIsResetting] = useState(false);

  const llmStatus       = health?.llm?.status ?? 'unknown';
  const isHealthy       = llmStatus === 'healthy';
  const exhaustedKeys   = health?.llm?.groq_keys_exhausted ?? 0;
  const showResetButton = exhaustedKeys > 0;

  const handleResetKeys = async () => {
    if (isResetting) return;
    setIsResetting(true);
    try {
      await api.resetKeys();
      await refetch();
    } catch (err) {
      console.error('Failed to reset keys:', err);
    } finally {
      setIsResetting(false);
    }
  };

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
            {exhaustedKeys > 0 && (
              <span className="keys-exhausted-badge">
                <KeyRound size={8} />
                {exhaustedKeys} key{exhaustedKeys !== 1 ? 's' : ''} exhausted
              </span>
            )}
          </span>
        )}
      </div>

      {showResetButton && (
        <button
          className="reset-keys-btn"
          onClick={handleResetKeys}
          disabled={isResetting}
          title={`Reset ${exhaustedKeys} exhausted Groq key${exhaustedKeys !== 1 ? 's' : ''}`}
          aria-label="Reset exhausted Groq API keys"
        >
          <RotateCcw size={12} className={isResetting ? 'spin-icon' : ''} />
          <span>Reset</span>
        </button>
      )}
    </div>
  );
}
