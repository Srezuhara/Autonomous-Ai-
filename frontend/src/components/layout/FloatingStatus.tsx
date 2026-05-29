import { useState } from 'react';
import { Activity, KeyRound, RotateCcw, AlertTriangle, Clock3 } from 'lucide-react';
import { useHealth } from '../../hooks/useHealth';
import { api } from '../../api/client';
import './FloatingStatus.css';

/**
 * FloatingStatus — Phase 20 (Gap B UI fix)
 *
 * Updated to consume the new exhausted_70b / exhausted_8b / fully_exhausted
 * breakdown fields returned by the v3.6.1 llm_client.get_key_status() via
 * the /health endpoint.
 *
 * Previous version only used `exhausted_keys` (the union count) to decide
 * whether to show the reset button, but showed a single generic message.
 *
 * New behaviour:
 *   fully_exhausted > 0 AND equals total_keys
 *     → "All keys exhausted — builds blocked" (red dot, urgent)
 *   exhausted_70b > 0, exhausted_8b == 0
 *     → "Heavy model exhausted — fast model OK" (yellow, non-critical)
 *   exhausted_8b > 0, exhausted_70b == 0
 *     → "Fast model exhausted — heavy model OK" (yellow, non-critical)
 *   both > 0 but not all fully exhausted
 *     → "X keys partially exhausted" (yellow)
 *   exhausted_keys == 0
 *     → Normal healthy display
 *
 * The "Reset Keys" button appears whenever exhausted_keys > 0 (union),
 * matching the fixed backend counter — previously it only appeared when
 * the intersection count was > 0 (i.e. never, if only one model was exhausted).
 */

export function FloatingStatus() {
  const { health, refetch } = useHealth();
  const [isResetting, setIsResetting] = useState(false);

  const llmStatus    = health?.llm?.status ?? 'unknown';
  const isHealthy    = llmStatus === 'healthy';

  // Standard union count — > 0 means at least one key hit at least one model
  const exhaustedKeys  = health?.llm?.groq_keys_exhausted ?? 0;
  const totalKeys      = health?.llm?.groq_keys_total      ?? 0;

  // Breakdown fields (v3.6.1 llm_client — may be absent on old deployments)
  const llmAny         = health?.llm as Record<string, unknown> | undefined;
  const exhausted70b   = (llmAny?.exhausted_70b   as number | undefined) ?? null;
  const exhausted8b    = (llmAny?.exhausted_8b    as number | undefined) ?? null;
  const fullyExhausted = (llmAny?.fully_exhausted as number | undefined) ?? null;
  const rateLimitModels = health?.llm?.rate_limits?.models ?? [];
  const waitingModel = [...rateLimitModels]
    .filter((model) => model.cooldown_seconds > 0)
    .sort((a, b) => b.cooldown_seconds - a.cooldown_seconds)[0];
  const dailyLimitedModel = rateLimitModels.find((model) => model.daily_limited);

  const showResetButton = exhaustedKeys > 0;

  const rateLimitMessage = (): { text: string; severity: 'warn' | 'error' | null } => {
    if (dailyLimitedModel) {
      return {
        text: `Groq daily quota reached (${dailyLimitedModel.model})`,
        severity: 'error',
      };
    }
    if (waitingModel) {
      const seconds = Math.ceil(waitingModel.cooldown_seconds);
      return {
        text: `Groq waiting ${seconds}s for token reset`,
        severity: 'warn',
      };
    }
    return { text: '', severity: null };
  };

  // ── Derive the most informative status message ─────────────────────────────
  const keyStatusMessage = (): { text: string; severity: 'warn' | 'error' | null } => {
    if (exhaustedKeys === 0 || totalKeys === 0) return { text: '', severity: null };

    // All keys completely dead (both models) — builds will stall
    if (fullyExhausted !== null && fullyExhausted >= totalKeys) {
      return {
        text:     'All keys exhausted — builds blocked',
        severity: 'error',
      };
    }

    // Only heavy model (70b) exhausted — fast-model calls still work
    if (exhausted70b !== null && exhausted8b !== null) {
      if (exhausted70b > 0 && exhausted8b === 0) {
        return {
          text:     `${exhausted70b} key${exhausted70b !== 1 ? 's' : ''} exhausted (heavy model only)`,
          severity: 'warn',
        };
      }
      // Only fast model (8b) exhausted
      if (exhausted8b > 0 && exhausted70b === 0) {
        return {
          text:     `${exhausted8b} key${exhausted8b !== 1 ? 's' : ''} exhausted (fast model only)`,
          severity: 'warn',
        };
      }
      // Both models have some exhausted keys
      if (exhausted70b > 0 && exhausted8b > 0) {
        return {
          text:     `${exhaustedKeys} key${exhaustedKeys !== 1 ? 's' : ''} exhausted (both models)`,
          severity: 'warn',
        };
      }
    }

    // Fallback: breakdown fields not yet available (old backend deployment)
    return {
      text:     `${exhaustedKeys} key${exhaustedKeys !== 1 ? 's' : ''} exhausted`,
      severity: 'warn',
    };
  };

  const { text: keyMsg, severity: keySeverity } = keyStatusMessage();
  const { text: rateMsg, severity: rateSeverity } = rateLimitMessage();

  // Override dot colour when all keys are completely dead
  const dotClass =
    rateSeverity === 'error' || keySeverity === 'error'
      ? 'dot--error'
      : isHealthy
      ? 'dot--healthy'
      : 'dot--degraded';

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
      <div className={`floating-status-dot ${dotClass}`} />

      <div className="floating-status-text">
        <span className="floating-status-title">
          {health ? 'Backend Online' : 'Connecting…'}
        </span>

        {health && (
          <span className="floating-status-sub">
            <Activity size={9} />
            LLM: {llmStatus} · {health.worker_pool?.active ?? 0} active

            {rateMsg && (
              <span
                className={`keys-exhausted-badge${rateSeverity === 'error' ? ' keys-exhausted-badge--error' : ''}`}
                title={rateSeverity === 'error'
                  ? 'Groq reported a daily organization/model quota limit. Wait for quota reset or use a higher-limit Groq plan.'
                  : 'Groq reported a temporary token/request rate limit. The backend is waiting and will retry without rotating keys.'}
              >
                {rateSeverity === 'error'
                  ? <AlertTriangle size={8} />
                  : <Clock3 size={8} />
                }
                {rateMsg}
              </span>
            )}

            {keyMsg && (
              <span
                className={`keys-exhausted-badge${keySeverity === 'error' ? ' keys-exhausted-badge--error' : ''}`}
                title={keySeverity === 'error'
                  ? 'All Groq API keys are exhausted. Click Reset to restore after the daily limit resets (midnight UTC).'
                  : 'Some Groq API keys have hit their daily limit. Click Reset after midnight UTC to restore them.'}
              >
                {keySeverity === 'error'
                  ? <AlertTriangle size={8} />
                  : <KeyRound size={8} />
                }
                {keyMsg}
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
          title={
            keySeverity === 'error'
              ? 'All keys exhausted — reset after midnight UTC when limits refresh'
              : `Reset ${exhaustedKeys} exhausted key${exhaustedKeys !== 1 ? 's' : ''} — use after midnight UTC`
          }
          aria-label="Reset exhausted Groq API keys"
        >
          <RotateCcw size={12} className={isResetting ? 'spin-icon' : ''} />
          <span>Reset</span>
        </button>
      )}
    </div>
  );
}
