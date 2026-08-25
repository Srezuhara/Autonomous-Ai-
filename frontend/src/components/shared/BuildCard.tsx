import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ChevronRight } from 'lucide-react';
import type { Project } from '../../api/client';
import { isDownloadable } from '../../api/client';
import { StatusBadge } from '../shared/StatusBadge';
import { formatScoreOutOfTen } from '../../lib/scores';
import { appItem, liftable, layoutSpring } from '../../lib/motion';
import './BuildCard.css';

/**
 * `motion.create` rather than wrapping the <Link> in a <motion.div>: the row's
 * flex layout, its padding and its `:focus-visible` outline all belong to the
 * anchor itself, so an extra wrapper element would either break the row or
 * force every one of those rules to be duplicated onto the wrapper.
 */
const MotionLink = motion.create(Link);

interface BuildCardProps {
  project: Project;
}

/**
 * BuildCard — one row in the build index.
 *
 * On `.panel panel--interactive` rather than the legacy `.card`, so a row here
 * and a surface anywhere else in the app share one radius, one hairline and one
 * hover treatment.
 *
 * Scores are `.ulabel` + `.figure`: mono and tabular, so the three columns line
 * up down the list instead of jittering row to row (the old `.score-chip-value`
 * was set in the proportional display face). They are deliberately *not*
 * colour-banded here — the StatusBadge already carries colour in every row, and
 * three more coloured figures per row would drown it. The banded scale lives on
 * ProjectDetail, where there are only three of them on the screen.
 *
 * ── Motion ────────────────────────────────────────────────────────────────
 * Three separate jobs, and they are deliberately different sizes:
 *
 *   `layout`     — when a status filter changes, the rows that survive slide
 *                  to their new positions instead of teleporting. This is the
 *                  one that makes filtering legible: you can see that a row
 *                  moved rather than being replaced.
 *   `appItem`    — enter/exit, driven by the list's stagger parent.
 *   `liftable`   — 2px hover lift. No scale; see lib/motion.
 *
 * `layout` is scoped to `"position"` so the browser only interpolates where
 * the row is, not how big it is. A full layout animation would also animate
 * the row's height, and a row whose height is mid-flight while its text is
 * already at final size shows the text clipped for a few frames.
 */
export function BuildCard({ project }: BuildCardProps) {
  // Phase 21: done_with_context builds have real scores too — show them.
  const isDone = isDownloadable(project.status);
  const displayName = project.app_name || project.build_id.substring(0, 8).toUpperCase();
  const promptPreview = project.prompt.length > 110
    ? project.prompt.substring(0, 110) + '…'
    : project.prompt;

  return (
    <MotionLink
      to={`/projects/${project.build_id}`}
      className="panel panel--interactive build-card"
      layout="position"
      variants={appItem}
      transition={layoutSpring}
      {...liftable}
    >
      <div className="build-card__info">
        <div className="build-card__head">
          <span className="build-card__name">{displayName}</span>
          <StatusBadge status={project.status} />
        </div>

        <p className="build-card__prompt">{promptPreview}</p>

        <div className="build-card__meta">
          <span>
            {new Date(project.created_at).toLocaleDateString('en-US', {
              month: 'short', day: 'numeric', year: 'numeric',
            })}
          </span>
          {project.app_type && <span className="tag">{project.app_type}</span>}
          {project.complexity && <span className="tag">{project.complexity}</span>}
          {project.duration_seconds != null && (
            <span>{Math.round(project.duration_seconds)}s</span>
          )}
        </div>
      </div>

      {isDone && (
        <div className="build-card__scores">
          <Score label="Rev" value={project.review_score} />
          <Score label="Dbg" value={project.debug_score} />
          <Score label="Tst" value={project.test_score} />
        </div>
      )}

      <ChevronRight size={18} className="build-card__arrow" aria-hidden />
    </MotionLink>
  );
}

/** All three scores normalised to one scale — see lib/scores.ts. */
function Score({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div className="build-card__score">
      <span className="ulabel">{label}</span>
      <span className="figure figure--md">{formatScoreOutOfTen(value)}</span>
    </div>
  );
}
