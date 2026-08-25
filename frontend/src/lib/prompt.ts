/**
 * prompt.ts — the prompt contract, in one place.
 *
 * There are two textareas in the product (NewBuild's composer and the rebuild
 * modal) and they used to disagree: the composer allowed 2000 characters while
 * the modal counted down from 500 and the API rejected anything over 500 with
 * a 422. The backend limit is now 2000; this module is what both fields read,
 * so a third field cannot reintroduce the drift.
 */

/** Must stay in step with `BuildRequest.prompt` max_length in api/models.py. */
export const MAX_CHARS = 2000;

/** Below this a prompt is too thin for the intent analyser to do anything with. */
export const MIN_CHARS = 11;

export type ReadoutTone = 'idle' | 'ready' | 'warn' | 'error';

export interface PromptState {
  used:        number;
  trimmed:     number;
  isOverLimit: boolean;
  /** Long enough, short enough — the caller still adds its own in-flight guard. */
  isValid:     boolean;
  /** Fraction of the budget consumed, for the meter. */
  usedPct:     number;
  readout:     { text: string; tone: ReadoutTone };
}

/**
 * One honest readout instead of a bare countdown. "1847 chars left" tells the
 * user nothing they need at 12 characters in; what they need to know is
 * whether the button will work.
 */
export function promptState(prompt: string, idleText = 'Describe what you want built'): PromptState {
  const used        = prompt.length;
  const trimmed     = prompt.trim().length;
  const isOverLimit = used > MAX_CHARS;

  const readout: { text: string; tone: ReadoutTone } =
    isOverLimit
      ? { text: `${used - MAX_CHARS} over the ${MAX_CHARS} limit`, tone: 'error' }
      : used === 0
      ? { text: idleText, tone: 'idle' }
      : trimmed < MIN_CHARS
      ? { text: `${MIN_CHARS - trimmed} more characters to start`, tone: 'warn' }
      : { text: `${used} / ${MAX_CHARS}`, tone: 'ready' };

  return {
    used,
    trimmed,
    isOverLimit,
    isValid: trimmed >= MIN_CHARS && !isOverLimit,
    usedPct: Math.min(100, (used / MAX_CHARS) * 100),
    readout,
  };
}
