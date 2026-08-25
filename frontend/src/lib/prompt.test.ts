import { describe, it, expect } from 'vitest';
import { promptState, MAX_CHARS, MIN_CHARS } from './prompt';

describe('prompt contract', () => {
  it('matches the backend limit', () => {
    // If this fails, api_platform/models.py and the composer disagree again —
    // which is the bug that let the UI accept a prompt the API rejected with
    // a 422 the user never saw explained.
    expect(MAX_CHARS).toBe(2000);
  });

  describe('readout state machine', () => {
    it('is idle with an empty field', () => {
      const s = promptState('');
      expect(s.readout.tone).toBe('idle');
      expect(s.isValid).toBe(false);
    });

    it('uses the caller-supplied idle text', () => {
      expect(promptState('', 'Describe what you want changed').readout.text)
        .toBe('Describe what you want changed');
    });

    it('warns and counts up while the prompt is too short', () => {
      const s = promptState('short');
      expect(s.readout.tone).toBe('warn');
      expect(s.readout.text).toBe(`${MIN_CHARS - 5} more characters to start`);
      expect(s.isValid).toBe(false);
    });

    it('turns ready at exactly the minimum', () => {
      const s = promptState('a'.repeat(MIN_CHARS));
      expect(s.readout.tone).toBe('ready');
      expect(s.isValid).toBe(true);
    });

    it('counts trimmed length, not raw length', () => {
      // Whitespace should not buy a user past the minimum.
      const padded = '   ' + 'a'.repeat(MIN_CHARS - 1) + '   ';
      expect(promptState(padded).isValid).toBe(false);
    });

    it('reports the budget once the prompt is usable', () => {
      const s = promptState('a'.repeat(50));
      expect(s.readout.text).toBe(`50 / ${MAX_CHARS}`);
    });

    it('is still valid at exactly the limit', () => {
      const s = promptState('a'.repeat(MAX_CHARS));
      expect(s.isOverLimit).toBe(false);
      expect(s.isValid).toBe(true);
    });

    it('errors one character past the limit and says by how much', () => {
      const s = promptState('a'.repeat(MAX_CHARS + 7));
      expect(s.isOverLimit).toBe(true);
      expect(s.isValid).toBe(false);
      expect(s.readout.tone).toBe('error');
      expect(s.readout.text).toBe(`7 over the ${MAX_CHARS} limit`);
    });
  });

  describe('budget meter', () => {
    it('is empty at zero', () => {
      expect(promptState('').usedPct).toBe(0);
    });

    it('tracks the fraction consumed', () => {
      expect(promptState('a'.repeat(MAX_CHARS / 2)).usedPct).toBe(50);
    });

    it('clamps at 100 rather than overflowing its track', () => {
      expect(promptState('a'.repeat(MAX_CHARS * 3)).usedPct).toBe(100);
    });
  });
});
