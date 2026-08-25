import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { KeyRound, RotateCcw, AlertTriangle, Clock3 } from 'lucide-react';
import { useHealth } from '../../hooks/useHealth';
import { api } from '../../api/client';
import { popIn, appItem, EASE, DURATION } from '../../lib/motion';
import './FloatingStatus.css';

/**
 * FloatingStatus — the persistent backend health pill.
 *
 * Behaviour (Phase 20, unchanged) consumes the exhausted_70b / exhausted_8b /
 * fully_exhausted breakdown from /health:
 *
 *   fully_exhausted > 0 AND == total_keys → "All keys exhausted" (error)
 *   exhausted_70b only                    → heavy model exhausted (warn)
 *   exhausted_8b only                     → fast model exhausted (warn)
 *   both                                  → N keys exhausted (warn)
 *   none                                  → healthy
 *
 * ── Redesign notes ────────────────────────────────────────────────────────
 * This element is on screen on every app route, permanently, in the corner of
 * the user's vision. Two things had to change:
 *
 * 1. The dot pulsed on a 2.5s infinite loop. A light that blinks forever is
 *    not a signal — it is ambient noise, and it is the single worst offender
 *    against the "nothing loops" motion rule. The dot is now static and
 *    carries its state in colour alone.
 *
 * 2. It rendered the full "LLM: healthy · 0 active" telemetry line at all
 *    times. When everything is fine, the correct amount of detail is none.
 *    The pill is now a dot plus one word when healthy, and expands to the full
 *    breakdown only when something actually needs attention (or on hover, for
 *    anyone who wants to check).
 *
 * `dot--error` was also missing from the stylesheet entirely, so the "all keys
 * exhausted" state — the one state that blocks builds — rendered with no
 * background colour at all. It is defined now via the shared `.sdot` scale.
 *
 * ── Motion ────────────────────────────────────────────────────────────────
 * Three additions, all tied to a real change of state, none of them looping:
 *
 *   - The pill slides up into the corner once, on first health response. It
 *     used to blink into existence at full opacity in the user's periphery.
 *   - The dot re-pops when the *tone* changes, and only then. Keying it on
 *     `tone` rather than on the health object means the 5-second poll does not
 *     retrigger it while everything is fine.
 *   - The severity lines disclose as they arrive.
 *
 * The hover expansion stays in CSS (`grid-template-rows`). Driving it from
 * React would re-render the widget on every pointer crossing of a fixed
 * element that sits under the cursor's path on every screen.
 */

export function FloatingStatus() {
  const { health, refetch } = useHealth();
  const [isResetting, setIsResetting] = useState(false);

  const llmStatus = health?.llm?.status ?? 'unknown';
  const isHealthy = llmStatus === 'healthy';

  // Union count — > 0 means at least one key hit at least one model
  const exhaustedKeys = health?.llm?.groq_keys_exhausted ?? 0;
  const totalKeys     = health?.llm?.groq_keys_total      ?? 0;

  // Breakdown fields (v3.6.1 llm_client — may be absent on old deployments)
  const llmAny          = health?.llm as Record<string, unknown> | undefined;
  const exhausted70b    = (llmAny?.exhausted_70b   as number | undefined) ?? null;
  const exhausted8b     = (llmAny?.exhausted_8b    as number | undefined) ?? null;
  const fullyExhausted  = (llmAny?.fully_exhausted as number | undefined) ?? null;
  const rateLimitModels = health?.llm?.rate_limits?.models ?? [];

  const waitingModel = [...rateLimitModels]
    .filter((model) => model.cooldown_seconds > 0)
    .sort((a, b) => b.cooldown_seconds - a.cooldown_seconds)[0];
  const dailyLimitedModel = rateLimitModels.find((model) => model.daily_limited);

  const showResetButton = exhaustedKeys > 0;
  const activeWorkers   = health?.worker_pool?.active ?? 0;

  const rateLimitMessage = (): { text: string; severity: 'warn' | 'error' | null } => {
    if (dailyLimitedModel) {
      return {
        text: `Groq daily quota reached (${dailyLimitedModel.model})`,
        severity: 'error',
      };
    }
    if (waitingModel) {
      const seconds = Math.ceil(waitingModel.cooldown_seconds);
      return { text: `Groq waiting ${seconds}s for token reset`, severity: 'warn' };
    }
    return { text: '', severity: null };
  };

  // ── Derive the most informative status message ─────────────────────────────
  const keyStatusMessage = (): { text: string; severity: 'warn' | 'error' | null } => {
    if (exhaustedKeys === 0 || totalKeys === 0) return { text: '', severity: null };

    // All keys completely dead (both models) — builds will stall
    if (fullyExhausted !== null && fullyExhausted >= totalKeys) {
      return { text: 'All keys exhausted — builds blocked', severity: 'error' };
    }

    if (exhausted70b !== null && exhausted8b !== null) {
      if (exhausted70b > 0 && exhausted8b === 0) {
        return {
          text: `${exhausted70b} key${exhausted70b !== 1 ? 's' : ''} exhausted (heavy model only)`,
          severity: 'warn',
        };
      }
      if (exhausted8b > 0 && exhausted70b === 0) {
        return {
          text: `${exhausted8b} key${exhausted8b !== 1 ? 's' : ''} exhausted (fast model only)`,
          severity: 'warn',
        };
      }
      if (exhausted70b > 0 && exhausted8b > 0) {
        return {
          text: `${exhaustedKeys} key${exhaustedKeys !== 1 ? 's' : ''} exhausted (both models)`,
          severity: 'warn',
        };
      }
    }

    // Fallback: breakdown fields not available (old backend deployment)
    return {
      text: `${exhaustedKeys} key${exhaustedKeys !== 1 ? 's' : ''} exhausted`,
      severity: 'warn',
    };
  };

  const { text: keyMsg,  severity: keySeverity }  = keyStatusMessage();
  const { text: rateMsg, severity: rateSeverity } = rateLimitMessage();

  const hasError   = rateSeverity === 'error' || keySeverity === 'error';
  const hasWarning = !hasError && (rateSeverity === 'warn' || keySeverity === 'warn');

  const tone = !health ? 'idle' : hasError ? 'error' : hasWarning ? 'warn' : isHealthy ? 'ok' : 'warn';

  /**
   * Collapsed when nothing is wrong. The detail rows are always in the DOM so
   * screen readers and the hover-expand both get them without a re-render; CSS
   * decides whether they occupy space.
   */
  const isExpanded = !!(keyMsg || rateMsg);

  const headline = !health
    ? 'Connecting…'
    : hasError
    ? 'Backend degraded'
    : hasWarning
    ? 'Backend limited'
    : 'Backend online';

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
    <motion.div
      className={`fstatus${isExpanded ? ' fstatus--expanded' : ''}`}
      role="status"
      aria-live="polite"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: DURATION.normal, ease: EASE.out, delay: 0.15 }}
    >
      <div className="fstatus__row">
        {/* Keyed on tone, so it pops when the backend's health actually
            changes and stays perfectly still through every poll that reports
            the same thing. */}
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={tone}
            className={`sdot sdot--${tone}`}
            variants={popIn}
            initial="hidden"
            animate="visible"
            exit="exit"
            aria-hidden
          />
        </AnimatePresence>

        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={headline}
            className="fstatus__headline"
            initial={{ opacity: 0, y: 3 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -3 }}
            transition={{ duration: DURATION.fast, ease: EASE.out }}
          >
            {headline}
          </motion.span>
        </AnimatePresence>

        {health && (
          <span className="fstatus__meta figure">
            {activeWorkers}
            <span className="figure__unit">active</span>
          </span>
        )}

        <AnimatePresence>
        {showResetButton && (
          <motion.button
            key="reset"
            variants={appItem}
            initial="hidden"
            animate="visible"
            exit="exit"
            whileTap={{ scale: 0.96 }}
            className="fstatus__reset"
            onClick={handleResetKeys}
            disabled={isResetting}
            title={
              keySeverity === 'error'
                ? 'All keys exhausted — reset after midnight UTC when limits refresh'
                : `Reset ${exhaustedKeys} exhausted key${exhaustedKeys !== 1 ? 's' : ''} — use after midnight UTC`
            }
            aria-label="Reset exhausted Groq API keys"
          >
            <RotateCcw size={11} className={isResetting ? 'spin-icon' : ''} />
            Reset
          </motion.button>
        )}
        </AnimatePresence>
      </div>

      {/* Detail — collapsed to zero height unless something needs attention.
          Hovering the pill reveals it either way. */}
      <div className="fstatus__detail">
        <div className="fstatus__detail-inner">
          <span className="fstatus__line">
            <span className="ulabel">LLM</span>
            {llmStatus}
          </span>

          {/* The severity lines arrive mid-session — a key exhausts, a rate
              limit clears — and each one changes the pill's height. They fade
              in place rather than disclosing, because the container above them
              is already animating its own height in CSS and two height
              animations on nested elements visibly stutter against each
              other. */}
          <AnimatePresence initial={false}>
          {rateMsg && (
            <motion.span
              key={`rate-${rateMsg}`}
              variants={appItem}
              initial="hidden"
              animate="visible"
              exit="exit"
              className={`fstatus__line fstatus__line--${rateSeverity}`}
              title={rateSeverity === 'error'
                ? 'Groq reported a daily organization/model quota limit. Wait for quota reset or use a higher-limit Groq plan.'
                : 'Groq reported a temporary token/request rate limit. The backend is waiting and will retry without rotating keys.'}
            >
              {rateSeverity === 'error' ? <AlertTriangle size={10} /> : <Clock3 size={10} />}
              {rateMsg}
            </motion.span>
          )}
          </AnimatePresence>

          <AnimatePresence initial={false}>
          {keyMsg && (
            <motion.span
              key={`key-${keyMsg}`}
              variants={appItem}
              initial="hidden"
              animate="visible"
              exit="exit"
              className={`fstatus__line fstatus__line--${keySeverity}`}
              title={keySeverity === 'error'
                ? 'All Groq API keys are exhausted. Click Reset to restore after the daily limit resets (midnight UTC).'
                : 'Some Groq API keys have hit their daily limit. Click Reset after midnight UTC to restore them.'}
            >
              {keySeverity === 'error' ? <AlertTriangle size={10} /> : <KeyRound size={10} />}
              {keyMsg}
            </motion.span>
          )}
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  );
}
