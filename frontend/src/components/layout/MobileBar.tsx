import { AnimatePresence, motion } from 'framer-motion';
import { Menu, X, Zap } from 'lucide-react';
import { EASE, DURATION, pressableSubtle } from '../../lib/motion';
import './MobileBar.css';

/**
 * MobileBar — the compact top bar that replaces the sidebar below 900px.
 *
 * Below that width the fixed 240px column left roughly 50–80px for content,
 * which `body { overflow-x: hidden }` then silently clipped: the app looked
 * empty rather than broken, so the missing navigation was easy to miss. The
 * column now slides out from behind this bar.
 *
 * It carries the route name because, with the sidebar closed, nothing else on
 * a scrolled page says which screen you are on.
 *
 * ── Motion ────────────────────────────────────────────────────────────────
 * The toggle is the same button in both states, so its icon crossfades with a
 * quarter turn rather than being swapped outright: the rotation is what makes
 * the two glyphs read as one control changing meaning instead of two controls
 * trading places. `mode="wait"` keeps exactly one glyph in the 18px box.
 *
 * The route title animates on change for the same reason the dashboard's build
 * count does — on a screen with no sidebar, it is the only thing that confirms
 * the navigation landed.
 */
export function MobileBar({ title, navOpen, onOpen }: {
  title: string;
  navOpen: boolean;
  onOpen: () => void;
}) {
  return (
    <header className="mobile-bar">
      <motion.button
        type="button"
        className="mobile-bar__toggle"
        onClick={onOpen}
        aria-label={navOpen ? 'Close navigation' : 'Open navigation'}
        aria-expanded={navOpen}
        aria-controls="app-sidebar"
        {...pressableSubtle}
      >
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={navOpen ? 'close' : 'open'}
            className="mobile-bar__icon"
            initial={{ opacity: 0, rotate: navOpen ? -90 : 90 }}
            animate={{ opacity: 1, rotate: 0 }}
            exit={{ opacity: 0, rotate: navOpen ? 90 : -90 }}
            transition={{ duration: DURATION.fast, ease: EASE.out }}
          >
            {navOpen
              ? <X size={18} strokeWidth={1.9} />
              : <Menu size={18} strokeWidth={1.9} />}
          </motion.span>
        </AnimatePresence>
      </motion.button>

      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={title}
          className="mobile-bar__title"
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: DURATION.fast, ease: EASE.out }}
        >
          {title}
        </motion.span>
      </AnimatePresence>

      <span className="mobile-bar__mark" aria-hidden>
        <Zap size={13} strokeWidth={2.25} />
      </span>
    </header>
  );
}
