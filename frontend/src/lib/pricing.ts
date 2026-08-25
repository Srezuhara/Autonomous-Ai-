/**
 * pricing.ts — token rates and their formatting, in one place.
 *
 * The per-million rates were literals in two files (ProjectDetail's cost line
 * and Statistics' token section), as was the `fmt` thousands/millions helper.
 * Two copies of a number that changes whenever the provider's price list does
 * is a drift waiting to happen — and the Statistics legend printed the rates
 * as prose beside them, so a stale copy would have been visibly wrong.
 */

/** USD per 1M tokens. Update here and every surface follows. */
export const RATE_INPUT_PER_M  = 0.59;
export const RATE_OUTPUT_PER_M = 0.79;

/**
 * A single blended rate for estimating a build whose input/output split is not
 * known — only the total. Deliberately not the mean of the two rates: real
 * builds are input-heavy, so this sits nearer the input price.
 */
export const RATE_BLENDED_PER_M = 0.35;

/** Compact token counts: 1_234 → "1.2K", 4_500_000 → "4.50M". */
export function formatTokens(n: number, zeroAs = '0'): string {
  if (n === 0) return zeroAs;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function costOf(promptTokens: number, completionTokens: number): number {
  return (promptTokens     / 1_000_000) * RATE_INPUT_PER_M
       + (completionTokens / 1_000_000) * RATE_OUTPUT_PER_M;
}

export function blendedCostOf(totalTokens: number): number {
  return (totalTokens / 1_000_000) * RATE_BLENDED_PER_M;
}

/**
 * Costs here are fractions of a cent. Three decimals with an explicit
 * "less than" floor is honest; `$0.00` reads as free.
 */
export function formatCost(usd: number, zeroAs = '—'): string {
  if (usd <= 0)     return zeroAs;
  if (usd < 0.001)  return '<$0.001';
  return `$${usd.toFixed(3)}`;
}

/** For the legend beside the split meter, so the prose cannot drift either. */
export function rateLabel(perM: number): string {
  return `$${perM.toFixed(2)} / 1M`;
}
