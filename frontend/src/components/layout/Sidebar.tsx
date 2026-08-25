import { NavLink, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Zap, LayoutDashboard, BarChart3, Plus, X } from 'lucide-react';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { NAV_RAIL_ID, layoutSpring, pressableSubtle } from '../../lib/motion';
import './Sidebar.css';

/**
 * Sidebar — app navigation.
 *
 * Two deliberate structural changes from the stock version:
 *
 * 1. "New Build" is no longer a nav item. It is the only verb in the product;
 *    everything else is inspection. Listing it as a peer of Dashboard and
 *    Statistics buried the one action the app exists to perform. It is now a
 *    button pinned above the nav.
 *
 * 2. The active state is a rail indicator plus accent text, not a filled pill.
 *    A tinted box with its own border reads as a fifth surface style on a
 *    screen that already has panels, chips and badges.
 *
 * The sidebar is `position: sticky` and never scrolls its own content, so the
 * backdrop-blur here is safe — unlike on `.card`, where it was removed.
 *
 * Below 900px it stops being a column and becomes an off-canvas drawer behind
 * `MobileBar`. `open` and `onClose` are only meaningful there; above the
 * breakpoint the CSS ignores both and the panel is simply always present.
 * The trap is armed by the caller, which knows whether it is a drawer.
 *
 * ── Motion ────────────────────────────────────────────────────────────────
 * The active-route rail is a single shared element (`layoutId`) rather than a
 * `::before` on whichever link happens to be active. It travels between the
 * nav items, which is the cheapest possible way to say "you moved from here to
 * there" — and it costs one animated node for the whole nav, not one per item.
 *
 * The drawer slide itself is left in CSS. It is already a `transform`
 * transition on `.sidebar--open`, it runs off the main thread, and it is
 * driven by a class the focus trap and `aria-hidden` already depend on.
 * Re-implementing it here would have bought nothing and given the open state
 * two owners.
 */

const NAV_LINKS = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/stats',     icon: BarChart3,       label: 'Statistics' },
] as const;

interface SidebarProps {
  /** Drawer state. Ignored above the breakpoint, where the column is static. */
  open?:     boolean;
  onClose?:  () => void;
  /** True only while the sidebar is actually behaving as a drawer. */
  isDrawer?: boolean;
}

export function Sidebar({ open = false, onClose, isDrawer = false }: SidebarProps) {
  const navigate = useNavigate();

  const trapped = isDrawer && open;
  const asideRef = useFocusTrap<HTMLElement>(trapped, () => onClose?.());

  const go = (to: string) => {
    navigate(to);
    onClose?.();
  };

  return (
    <aside
      ref={asideRef}
      id="app-sidebar"
      className={`sidebar${open ? ' sidebar--open' : ''}`}
      aria-label="Main navigation"
      aria-hidden={isDrawer && !open ? true : undefined}
      tabIndex={-1}
    >
      <div className="sidebar__inner">

        {/* Only reachable as a drawer; above the breakpoint there is nothing
            to close, so the control is not rendered at all rather than being
            hidden with CSS and left in the tab order. */}
        {isDrawer && (
          <button
            type="button"
            className="sidebar__close"
            onClick={() => onClose?.()}
            aria-label="Close navigation"
          >
            <X size={16} strokeWidth={2} />
          </button>
        )}

        <NavLink to="/" className="brand" aria-label="AppBuilder home" onClick={() => onClose?.()}>
          <span className="brand__mark" aria-hidden>
            <Zap size={15} strokeWidth={2.25} />
          </span>
          <span className="brand__text">
            <span className="brand__name">AppBuilder</span>
            <span className="brand__meta">autonomous</span>
          </span>
        </NavLink>

        {/* The one verb in the product. The CSS `:active` scale it used to
            rely on snaps back the instant the pointer lifts; the motion press
            releases on the same curve it depressed on, which is the difference
            between a button that clicks and one that just flickers. */}
        <motion.button
          type="button"
          className="sidebar__action"
          onClick={() => go('/build')}
          whileHover={{ y: -1 }}
          {...pressableSubtle}
        >
          <Plus size={15} strokeWidth={2.25} />
          New build
        </motion.button>

        <nav className="sidebar__nav" aria-label="Main">
          <span className="ulabel sidebar__nav-label">Browse</span>
          {NAV_LINKS.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) => `navlink${isActive ? ' navlink--active' : ''}`}
              onClick={() => onClose?.()}
            >
              {({ isActive }) => (
                <>
                  {/* Only the active item mounts the rail, so Framer sees one
                      node moving between two parents rather than two nodes
                      cross-fading. `aria-hidden`: the active route is already
                      announced by NavLink's `aria-current`. */}
                  {isActive && (
                    <motion.span
                      layoutId={NAV_RAIL_ID}
                      className="navlink__rail"
                      transition={layoutSpring}
                      aria-hidden
                    />
                  )}
                  <Icon size={16} strokeWidth={1.9} className="navlink__icon" />
                  <span>{label}</span>
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <footer className="sidebar__footer">
          <span className="ulabel">Pipeline</span>
          <span className="sidebar__footer-value figure figure--sm">
            9<span className="figure__unit">agents</span>
          </span>
        </footer>
      </div>
    </aside>
  );
}
