/**
 * scores.ts — the single interpretation of a pipeline score.
 *
 * The three score fields arrive in three different shapes and were being
 * decoded in two places, differently: ProjectDetail parsed all of them
 * properly, while BuildCard used `.toFixed(1)` on one and `.split('/')[0]` on
 * the other two — so "3/5" rendered as "3" beside a review score of "7.5",
 * two numbers on two different scales sitting in the same row.
 *
 * Everything that displays a score now goes through here.
 */

/**
 * Converts any score format to a 0-100 percentage.
 *   "7.5"                     → 75   (numeric out of 10)
 *   "7.5/10"                  → 75   (explicit /10)
 *   "3/5"                     → 60   (test score fraction)
 *   "0/0 (collection errors)" → 0
 *   7                         → 70   (bare number)
 */
export function parseScorePct(value: string | number | undefined | null): number {
  if (value == null) return 0;
  const str = String(value).trim();
  if (!str || str === '—') return 0;

  const fracMatch = str.match(/^(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)/);
  if (fracMatch) {
    const num = parseFloat(fracMatch[1]);
    const den = parseFloat(fracMatch[2]);
    if (den > 0) return Math.min(100, (num / den) * 100);
    return 0;
  }

  const n = parseFloat(str);
  if (!isNaN(n)) return Math.min(100, (n / 10) * 100);
  return 0;
}

/** True when the backend has no score for this field at all. */
export function hasScore(value: string | number | undefined | null): boolean {
  if (value == null) return false;
  const str = String(value).trim();
  return str !== '' && str !== '—';
}

/**
 * Compact display for dense rows: every score on one scale, out of 10, so
 * three figures in a list can actually be compared to each other.
 */
export function formatScoreOutOfTen(value: string | number | undefined | null): string {
  if (!hasScore(value)) return '—';
  const outOfTen = parseScorePct(value) / 10;
  // One decimal, but no trailing ".0" — "8" and "7.5" both read cleanly.
  return outOfTen.toFixed(1).replace(/\.0$/, '');
}

/**
 * Scores use the validated dark-surface viz palette rather than the light-UI
 * semantic colours — the same three-band scale the charts use, so a green here
 * and a green in Statistics mean the same thing.
 */
export function scoreColor(pct: number): string {
  if (pct >= 70) return 'var(--viz-done)';
  if (pct >= 40) return 'var(--viz-degraded)';
  return 'var(--viz-failed)';
}
