/**
 * components/ui/primitives.tsx
 * ============================
 * The shared visual vocabulary. Everything premium in this app is built from
 * these five pieces, so the look stays consistent instead of each page
 * inventing its own card.
 *
 *   <AmbientMesh/>  fixed, pure-CSS background field (replaced the WebGL shader)
 *   <Bezel/>        nested "machined hardware" container — outer shell + inner core
 *   <Eyebrow/>      microscopic pill label that precedes a heading
 *   <CTA/>          pill button with a nested icon capsule and press physics
 *   <Reveal/>       scroll-entry animation wrapper
 *
 * Performance notes, because this app must not stutter:
 *   - AmbientMesh is static CSS gradients. No canvas, no rAF loop, no GPU
 *     shader. It costs one paint and then nothing at all.
 *   - backdrop-blur appears ONLY on fixed/sticky surfaces, never on anything
 *     that scrolls — blurring a scrolling container forces a repaint per frame.
 *   - Reveal animates transform/opacity/filter only, and fires once.
 */
import { motion, type Variants } from 'framer-motion';
import type { ReactNode, CSSProperties } from 'react';
import { Link } from 'react-router-dom';
import { fadeUp, stagger, viewportOnce, EASE, DURATION } from '@/lib/motion';

/* ────────────────────────────────────────────────────────────────────────────
   AmbientMesh — the background field
   ──────────────────────────────────────────────────────────────────────────── */

/**
 * Three offset radial gradients + a fine grain layer, all fixed and inert.
 *
 * This is what replaced the Spline scene and the WebGL fragment shader. Those
 * ran a requestAnimationFrame loop for the entire session and were the single
 * largest source of jank; they also painted the page orange, fighting the
 * indigo palette. Gradients cost one composite and hold the brand colour.
 */
export function AmbientMesh({ intensity = 1 }: { intensity?: number }) {
  return (
    <div aria-hidden className="ambient-mesh" style={{ '--mesh-i': intensity } as CSSProperties}>
      <div className="ambient-mesh__orb ambient-mesh__orb--indigo" />
      <div className="ambient-mesh__orb ambient-mesh__orb--violet" />
      <div className="ambient-mesh__orb ambient-mesh__orb--cyan" />
      <div className="ambient-mesh__grain" />
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
   Bezel — double-bezel / Doppelrand container
   ──────────────────────────────────────────────────────────────────────────── */

interface BezelProps {
  children: ReactNode;
  className?: string;
  innerClassName?: string;
  /** Adds accent-tinted shell + glow. Use for the one card that matters most. */
  featured?: boolean;
  style?: CSSProperties;
}

/**
 * A container that reads as a glass plate seated in a metal tray, rather than a
 * flat rectangle on a flat background. The inner radius is computed from the
 * outer radius minus the shell padding so the two curves stay concentric —
 * mismatched radii are the tell of a cheap card.
 */
export function Bezel({ children, className = '', innerClassName = '', featured = false, style }: BezelProps) {
  return (
    <div className={`bezel ${featured ? 'bezel--featured' : ''} ${className}`} style={style}>
      <div className={`bezel__core ${innerClassName}`}>{children}</div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
   Eyebrow — the microscopic pill above a heading
   ──────────────────────────────────────────────────────────────────────────── */

export function Eyebrow({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <span className={`eyebrow ${className}`}>{children}</span>;
}

/* ────────────────────────────────────────────────────────────────────────────
   CTA — pill button with nested icon capsule
   ──────────────────────────────────────────────────────────────────────────── */

interface CTAProps {
  children: ReactNode;
  to?: string;
  href?: string;
  onClick?: () => void;
  variant?: 'primary' | 'ghost';
  icon?: ReactNode;
  className?: string;
  type?: 'button' | 'submit';
  disabled?: boolean;
}

/**
 * The trailing icon is never naked beside the label — it sits in its own
 * circular capsule flush with the button's inner padding. On hover the capsule
 * translates diagonally while the button itself barely moves, which creates
 * internal tension instead of the whole element sliding around.
 */
export function CTA({
  children, to, href, onClick, variant = 'primary',
  icon, className = '', type = 'button', disabled,
}: CTAProps) {
  const content = (
    <>
      <span className="cta__label">{children}</span>
      {icon && <span className="cta__capsule">{icon}</span>}
    </>
  );

  const cls = `cta cta--${variant} ${className}`;
  // Press feedback only. The hover translate lives in CSS on the capsule so it
  // does not need a re-render per pointer move.
  const press = { whileTap: disabled ? undefined : { scale: 0.985 } };
  const t = { duration: DURATION.fast, ease: EASE.out };

  if (to) {
    return (
      <motion.div {...press} transition={t} className="cta__wrap">
        <Link to={to} className={cls}>{content}</Link>
      </motion.div>
    );
  }
  if (href) {
    return (
      <motion.div {...press} transition={t} className="cta__wrap">
        <a href={href} target="_blank" rel="noreferrer" className={cls}>{content}</a>
      </motion.div>
    );
  }
  return (
    <motion.button
      {...press}
      transition={t}
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={cls}
    >
      {content}
    </motion.button>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
   Reveal — scroll entry
   ──────────────────────────────────────────────────────────────────────────── */

interface RevealProps {
  children: ReactNode;
  className?: string;
  /** Seconds of delay. Keep under ~0.3 or the page feels like it is loading. */
  delay?: number;
  variants?: Variants;
  as?: 'div' | 'section' | 'li' | 'span';
  style?: CSSProperties;
}

/**
 * Fires once when the element is 20% visible. Framer reads
 * prefers-reduced-motion itself, so a reduced-motion visitor gets the final
 * state with no transition and no layout difference.
 */
export function Reveal({
  children, className = '', delay = 0, variants = fadeUp, as = 'div', style,
}: RevealProps) {
  const Cmp = motion[as];
  return (
    <Cmp
      className={className}
      style={style}
      initial="hidden"
      whileInView="visible"
      viewport={viewportOnce}
      variants={variants}
      transition={{ delay }}
    >
      {children}
    </Cmp>
  );
}

/** Parent that releases its <Reveal> children in sequence. */
export function RevealGroup({
  children, className = '', step = 0.07, delay = 0, style,
}: { children: ReactNode; className?: string; step?: number; delay?: number; style?: CSSProperties }) {
  return (
    <motion.div
      className={className}
      style={style}
      initial="hidden"
      whileInView="visible"
      viewport={viewportOnce}
      variants={stagger(step, delay)}
    >
      {children}
    </motion.div>
  );
}

/** Child of RevealGroup — inherits the parent's stagger timing. */
export function RevealItem({
  children, className = '', variants = fadeUp, style,
}: { children: ReactNode; className?: string; variants?: Variants; style?: CSSProperties }) {
  return (
    <motion.div className={className} style={style} variants={variants}>
      {children}
    </motion.div>
  );
}
