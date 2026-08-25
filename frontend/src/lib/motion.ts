/**
 * lib/motion.ts — shared motion vocabulary
 * =========================================
 * One source of truth for timing, easing and variants so the whole app moves
 * with the same physics. Import these instead of hand-writing transitions.
 *
 * Motion weighting for this product (two different jobs, two different feels):
 *
 *   Landing / marketing  → polish-forward. 300–600ms, heavy glide easing,
 *                          staggered reveals. Motion is part of the pitch.
 *   Dashboard / build UI → restraint. Sub-200ms or nothing. These screens are
 *                          used hundreds of times a session; motion there is
 *                          friction, not delight.
 *
 * Rules enforced here:
 *   - transform / opacity / filter only. Never width, height, top, left.
 *   - no bare `ease` or `linear` — every curve is deliberate.
 *   - exits are always subtler than enters (attention is already moving on).
 *   - nothing loops. No pulsing, breathing or glowing attention-seekers.
 */
import type { Transition, Variants } from 'framer-motion';

/* ── Easing curves (mirror of the CSS custom properties) ──────────────────── */
export const EASE = {
  out:    [0.16, 1, 0.3, 1],
  in:     [0.4, 0, 1, 1],
  inOut:  [0.65, 0, 0.35, 1],
  /** Long, heavy, expensive-feeling. The signature curve for the landing. */
  glide:  [0.32, 0.72, 0, 1],
  spring: [0.34, 1.56, 0.64, 1],
} as const;

export const DURATION = {
  instant: 0.09,
  fast:    0.15,
  normal:  0.26,
  slow:    0.42,
  glide:   0.7,
} as const;

/** True when the visitor has asked the OS for less motion. */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/* ── Transitions ──────────────────────────────────────────────────────────── */

/** Marketing-surface transition: heavy, deliberate, unmistakably designed. */
export const glide: Transition = {
  duration: DURATION.glide,
  ease: EASE.glide,
};

/** App-surface transition: fast enough to feel instant, smooth enough to track. */
export const snappy: Transition = {
  duration: DURATION.fast,
  ease: EASE.out,
};

/* ── Variants ─────────────────────────────────────────────────────────────── */

/**
 * The primary reveal: fade up from below with a slight defocus resolving into
 * focus. The blur is what separates this from a stock fade — it reads as the
 * element settling into place rather than simply appearing.
 *
 * Pair with `viewportOnce` so it fires once, not on every scroll pass.
 */
export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 24, filter: 'blur(6px)' },
  visible: {
    opacity: 1,
    y: 0,
    filter: 'blur(0px)',
    transition: glide,
  },
};

/** Same idea, shorter throw — for items already near the fold. */
export const fadeUpTight: Variants = {
  hidden: { opacity: 0, y: 12, filter: 'blur(4px)' },
  visible: {
    opacity: 1,
    y: 0,
    filter: 'blur(0px)',
    transition: { duration: DURATION.slow, ease: EASE.glide },
  },
};

export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: DURATION.slow, ease: EASE.out } },
};

/**
 * Parent container that releases children in sequence. Stagger is small on
 * purpose — a long cascade looks like a slideshow, not a page.
 */
export function stagger(step = 0.07, delay = 0): Variants {
  return {
    hidden: {},
    visible: {
      transition: { staggerChildren: step, delayChildren: delay },
    },
  };
}

/** Scale-in for cards and popovers. Never starts at 0 — that reads as unnatural. */
export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.96 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { duration: DURATION.normal, ease: EASE.out },
  },
  // Exit is deliberately smaller than enter.
  exit: {
    opacity: 0,
    scale: 0.985,
    transition: { duration: DURATION.fast, ease: EASE.in },
  },
};

/**
 * Dialog enter/exit.
 *
 * The exit is deliberately not the enter played backwards: it drops the
 * translate and runs shorter, so the dialog recedes rather than retracing its
 * arrival. A modal that leaves exactly the way it came reads as an undo of the
 * open rather than as a dismissal.
 */
export const dialogIn: Variants = {
  hidden: { opacity: 0, y: 4 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: DURATION.fast, ease: EASE.out },
  },
  exit: {
    opacity: 0,
    transition: { duration: 0.12, ease: EASE.in },
  },
};

/** The overlay behind a dialog. Opacity only — it covers the whole viewport. */
export const backdropIn: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: DURATION.fast, ease: EASE.out } },
  exit:    { opacity: 0, transition: { duration: 0.12, ease: EASE.in } },
};

/** Panel/drawer slide. transform-only so it never triggers reflow. */
export const slideUp: Variants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: snappy },
  exit:    { opacity: 0, y: 4, transition: { duration: DURATION.instant, ease: EASE.in } },
};

/* ── Viewport presets ─────────────────────────────────────────────────────── */

/**
 * Fire once, slightly before the element is fully on screen. `amount: 0.2`
 * means "when 20% is visible" — enough that the motion is seen starting,
 * not discovered already finished.
 */
export const viewportOnce = { once: true, amount: 0.2 } as const;

/** For tall sections where waiting for 20% would feel late. */
export const viewportEarly = { once: true, amount: 0.05 } as const;

/* ── Hover physics ────────────────────────────────────────────────────────── */

/**
 * Press feedback. Scaling *down* on tap simulates physical depression — the
 * common mistake is scaling up, which feels like the button is escaping.
 */
export const pressable = {
  whileHover: { scale: 1.015 },
  whileTap: { scale: 0.985 },
  transition: { duration: DURATION.fast, ease: EASE.out },
} as const;

/** Subtler press for dense UI where a 1.5% grow would feel twitchy. */
export const pressableSubtle = {
  whileTap: { scale: 0.99 },
  transition: { duration: DURATION.instant, ease: EASE.out },
} as const;

/* ══════════════════════════════════════════════════════════════════════════
   APP SURFACES
   ══════════════════════════════════════════════════════════════════════════
   Everything above this line is marketing weight. Everything below is for the
   dashboard, the build screen and the report — surfaces a user opens dozens of
   times a session, where motion's only job is to explain *what changed*, never
   to be noticed for its own sake.

   The budget here is deliberately tight:
     - enters ≤ 180ms, exits ≤ 120ms
     - throw distance ≤ 8px (the landing uses 24px; that reads as slow here)
     - no blur — the defocus that sells a hero reveal is a cost you pay on
       every single repaint, and on a list of 50 rows it is visible jank
     - stagger step 0.03, capped: past ~8 items a cascade becomes a wipe
   ────────────────────────────────────────────────────────────────────────── */

/** One item in an app-surface list, grid or panel column. */
export const appItem: Variants = {
  hidden: { opacity: 0, y: 6 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: DURATION.fast, ease: EASE.out },
  },
  exit: {
    opacity: 0,
    y: -4,
    transition: { duration: DURATION.instant, ease: EASE.in },
  },
};

/**
 * Parent for `appItem` children.
 *
 * `staggerChildren` alone would keep adding delay forever, so a 40-row build
 * list would still be arriving two seconds later. The cap is applied by the
 * caller passing a smaller step for long lists; 0.03 × 8 = 240ms is the
 * intended ceiling for a normal grid.
 */
export function appStagger(step = 0.03, delay = 0): Variants {
  return {
    hidden: {},
    visible: { transition: { staggerChildren: step, delayChildren: delay } },
    exit:    { transition: { staggerChildren: 0.015, staggerDirection: -1 } },
  };
}

/**
 * A value or status that has just *changed* in place.
 *
 * Overshoots very slightly (1.06) and settles. This is the one place a spring
 * is correct in the app: a step turning green is a discrete event with a
 * physical feel, not a transition between two layouts. Anything above ~1.08
 * starts reading as a notification badge begging for attention.
 */
export const popIn: Variants = {
  hidden: { opacity: 0, scale: 0.6 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { type: 'spring', stiffness: 620, damping: 26, mass: 0.6 },
  },
  exit: {
    opacity: 0,
    scale: 0.7,
    transition: { duration: DURATION.instant, ease: EASE.in },
  },
};

/**
 * Height-auto disclosure, for detail that appears under an existing row.
 *
 * Height is normally forbidden here — it is a layout property and it does not
 * composite. It is allowed in exactly this shape because the alternative
 * (transform-only) cannot push the content below it out of the way, so the
 * disclosure would overlap whatever follows. Keep it to small regions.
 */
export const disclose: Variants = {
  hidden: { height: 0, opacity: 0 },
  visible: {
    height: 'auto',
    opacity: 1,
    transition: {
      height:  { duration: DURATION.normal, ease: EASE.out },
      opacity: { duration: DURATION.fast, ease: EASE.out, delay: 0.06 },
    },
  },
  exit: {
    height: 0,
    opacity: 0,
    transition: {
      height:  { duration: DURATION.fast, ease: EASE.in },
      opacity: { duration: DURATION.instant, ease: EASE.in },
    },
  },
};

/**
 * Route-level transition.
 *
 * Runs under `AnimatePresence mode="wait"`, so the exit and the enter are
 * sequential and their durations add up in the user's perception. The exit is
 * therefore barely there — 80ms of opacity, no movement. Moving the outgoing
 * page as well would double the apparent cost of every navigation, which is
 * the single most common way route transitions end up feeling sluggish.
 */
export const routeTransition: Variants = {
  hidden:  { opacity: 0, y: 5 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.18, ease: EASE.out } },
  exit:    { opacity: 0, transition: { duration: 0.08, ease: EASE.in } },
};

/**
 * Card hover for panels that are links.
 *
 * translateY, never scale: a scaled card resamples its own text, and on a list
 * of rows containing 11px mono figures that is visibly blurry mid-transition.
 * A 2px lift reads as the same affordance and stays pixel-sharp.
 */
export const liftable = {
  /**
   * The curve lives *inside* each gesture value rather than in a sibling
   * `transition` key. A top-level `transition` on a motion component is shared
   * with its `layout` animation, so spreading this onto a row that also lays
   * out would silently overwrite the layout spring with a 150ms tween — the
   * rows would slide linearly and land dead instead of settling.
   */
  whileHover: { y: -2, transition: { duration: DURATION.fast, ease: EASE.out } },
  whileTap:   { y: 0, scale: 0.995, transition: { duration: DURATION.instant, ease: EASE.out } },
} as const;

/** Shared-element id for the sidebar's active-route rail. */
export const NAV_RAIL_ID = 'nav-active-rail';

/** Shared-element id for the pressed state of a filter chip row. */
export const CHIP_ID = 'chip-active';

/** The layout spring used by every `layout` / `layoutId` animation in the app. */
export const layoutSpring: Transition = {
  type: 'spring',
  stiffness: 520,
  damping: 40,
  mass: 0.7,
};

/*
 * Reduced motion needs nothing extra here.
 *
 * Worth recording, because the opposite is easy to assume and the check is
 * fiddly to run: `<MotionConfig reducedMotion="user">` in main.tsx *does*
 * cover `layout` and `layoutId` projection animations, not only the animate
 * props. Verified by measurement — with the media query genuinely on, the
 * shared filter chip is already at its destination on the first sampled frame
 * (`transform: none`, 0px offset) rather than travelling its spring.
 *
 * The catch is that `page.emulateMedia()` is the spelling that actually turns
 * the query on for that check; a context-level `reducedMotion` option that
 * silently fails to apply makes the animation look broken when it is fine.
 */
