import type { ReactNode } from 'react';
import { motion } from 'framer-motion';
import { appItem } from '../../lib/motion';
import './StatTile.css';

/**
 * StatTile — the one KPI tile in the product.
 *
 * Dashboard and Statistics both opened with a four-up metric row, and both had
 * grown their own: `MetricCard` with an inline `style={{ color }}` on the icon,
 * and a set of inline-styled divs in Statistics. Two tiles meant two type
 * scales for the same kind of number, so the rows never lined up.
 *
 * This is `.panel` + `.ulabel` + `.figure` and nothing else. The figure is mono
 * and tabular, so a value that refreshes under a poll does not shift the row.
 * Icons are tertiary — they label the tile, they do not colour-code it; status
 * colour belongs to badges and charts, where it carries meaning.
 *
 * ── Motion ────────────────────────────────────────────────────────────────
 * The tile declares `appItem` but sets no `initial`/`animate` of its own, so
 * it animates only when it is dropped inside a parent running `appStagger` —
 * which is how both KPI rows use it. Rendered standalone it is inert, which is
 * what you want: a tile that fades itself in every time a poll re-renders the
 * row would flicker four times a minute on the dashboard.
 */
export function StatTile({ label, value, unit, icon, hint }: {
  label: string;
  value: ReactNode;
  unit?: string;
  icon?: ReactNode;
  hint?: string;
}) {
  return (
    <motion.div className="panel panel--pad stat-tile" variants={appItem}>
      <div className="stat-tile__head">
        <span className="ulabel">{label}</span>
        {icon && <span className="stat-tile__icon">{icon}</span>}
      </div>
      <div className="figure figure--lg stat-tile__value">
        {value}
        {unit && <span className="figure__unit">{unit}</span>}
      </div>
      {hint && <p className="stat-tile__hint">{hint}</p>}
    </motion.div>
  );
}
