import { describe, it, expect } from 'vitest';
import { parseScorePct, formatScoreOutOfTen, hasScore, scoreColor } from './scores';

/**
 * The three score fields arrive in three different shapes. Before this module
 * existed, BuildCard decoded them with `.toFixed(1)` on one and `.split('/')[0]`
 * on the other two, so "3/5" rendered as "3" beside a review score of "7.5" —
 * two numbers on two different scales in the same row.
 */
describe('parseScorePct', () => {
  it.each([
    ['7.5',      75],   // bare numeric, out of 10
    ['7.5/10',   75],   // explicit /10
    ['3/5',      60],   // test-score fraction
    ['0/0',       0],   // no tests collected — must not divide by zero
    ['10/10',   100],
    [7,          70],   // bare number
    ['8',        80],
  ])('reads %p as %i%%', (input, expected) => {
    expect(parseScorePct(input as string | number)).toBe(expected);
  });

  it('handles a fraction with a trailing note', () => {
    expect(parseScorePct('0/0 (collection errors)')).toBe(0);
  });

  it.each([undefined, null, '', '   ', '—'])('treats %p as zero', (input) => {
    expect(parseScorePct(input as undefined)).toBe(0);
  });

  it('never exceeds 100, even on an out-of-range score', () => {
    expect(parseScorePct('15/10')).toBe(100);
    expect(parseScorePct(42)).toBe(100);
  });

  it('returns zero for text it cannot read', () => {
    expect(parseScorePct('not a score')).toBe(0);
  });
});

describe('formatScoreOutOfTen', () => {
  it('puts every field on one scale so a row can be compared', () => {
    // The whole point: these three are natively /10, /10 and /5.
    expect(formatScoreOutOfTen(7.5)).toBe('7.5');
    expect(formatScoreOutOfTen('8/10')).toBe('8');
    expect(formatScoreOutOfTen('3/5')).toBe('6');
  });

  it('drops a trailing .0 so the column reads cleanly', () => {
    expect(formatScoreOutOfTen('10/10')).toBe('10');
    expect(formatScoreOutOfTen(8)).toBe('8');
  });

  it.each([undefined, null, '', '—'])('renders %p as an em dash', (input) => {
    expect(formatScoreOutOfTen(input as undefined)).toBe('—');
  });

  it('distinguishes a real zero from a missing score', () => {
    // "0/0 (collection errors)" is a measurement; undefined is an absence.
    expect(formatScoreOutOfTen('0/0')).toBe('0');
    expect(formatScoreOutOfTen(undefined)).toBe('—');
  });
});

describe('hasScore', () => {
  it.each([undefined, null, '', '  ', '—'])('is false for %p', (input) => {
    expect(hasScore(input as undefined)).toBe(false);
  });

  it.each(['0', '3/5', 7.5, 0])('is true for %p', (input) => {
    expect(hasScore(input as string | number)).toBe(true);
  });
});

describe('scoreColor', () => {
  it('uses the same three-band viz scale as the charts', () => {
    expect(scoreColor(85)).toBe('var(--viz-done)');
    expect(scoreColor(55)).toBe('var(--viz-degraded)');
    expect(scoreColor(20)).toBe('var(--viz-failed)');
  });

  it('puts the band boundaries at 70 and 40', () => {
    expect(scoreColor(70)).toBe('var(--viz-done)');
    expect(scoreColor(69.9)).toBe('var(--viz-degraded)');
    expect(scoreColor(40)).toBe('var(--viz-degraded)');
    expect(scoreColor(39.9)).toBe('var(--viz-failed)');
  });
});
