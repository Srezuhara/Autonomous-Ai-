import { useState, lazy, Suspense } from 'react';
import { Routes, Route, useLocation, matchPath } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { routeTransition } from './lib/motion';
import { Sidebar } from './components/layout/Sidebar';
import { MobileBar } from './components/layout/MobileBar';
import { FloatingStatus } from './components/layout/FloatingStatus';
import { useMediaQuery } from './hooks/useMediaQuery';

// Pages
import Landing       from './pages/Landing';
import Dashboard     from './pages/Dashboard';
import NewBuild      from './pages/NewBuild';
import BuildProgress from './pages/BuildProgress';
import ProjectDetail from './pages/ProjectDetail';
/**
 * Statistics is the only route that pulls in Recharts, and Recharts is the
 * single largest thing in the bundle. Split out, it stops being downloaded and
 * parsed by everyone who never opens the page — which, on a build tool, is
 * most sessions.
 */
const Statistics = lazy(() => import('./pages/Statistics'));

/**
 * Route names for the mobile bar. With the sidebar closed nothing else on a
 * scrolled page says which screen you are on, and the page's own `<h1>` is
 * often above the fold and gone.
 */
const ROUTE_TITLES: Array<[string, string]> = [
  ['/dashboard',    'Dashboard'],
  ['/build/:id',    'Build progress'],
  ['/build',        'New build'],
  ['/projects/:id', 'Build report'],
  ['/stats',        'Statistics'],
];

function routeTitle(pathname: string): string {
  const hit = ROUTE_TITLES.find(([pattern]) => matchPath(pattern, pathname));
  return hit ? hit[1] : 'AppBuilder';
}

/** Must stay in step with the drawer breakpoint in Sidebar.css / MobileBar.css. */
const DRAWER_QUERY = '(max-width: 899px)';

export default function App() {
  const location = useLocation();
  const isLanding = location.pathname === '/';
  const isDrawer = useMediaQuery(DRAWER_QUERY);

  /**
   * The drawer stores the route it was opened on rather than a bare boolean,
   * so navigating anywhere closes it as a consequence of the route changing —
   * no effect watching `location` and calling setState during a commit.
   */
  const [openedAt, setOpenedAt] = useState<string | null>(null);
  const navOpen = isDrawer && !isLanding && openedAt === location.pathname;

  const closeNav = () => setOpenedAt(null);

  return (
    <div className="layout-container">
      {!isLanding && (
        <Sidebar
          open={navOpen}
          onClose={closeNav}
          isDrawer={isDrawer}
        />
      )}

      {/* The drawer's dismiss target and its backdrop. Rendered whenever the
          sidebar is a drawer — not only while open — so it can fade out as
          well as in; `--open` drives both opacity and pointer-events. Above
          the breakpoint it is not rendered at all. */}
      {isDrawer && !isLanding && (
        <div
          className={`nav-scrim${navOpen ? ' nav-scrim--open' : ''}`}
          onClick={closeNav}
          aria-hidden
        />
      )}

      {/* `.main-content` is the scroll container, so the sticky bar has to
          live inside it. Only the routed content below is inert — the toggle
          itself stays reachable, and becomes the close control while open. */}
      <main className="main-content" style={isLanding ? { padding: 0 } : undefined}>
        {!isLanding && (
          <MobileBar
            title={routeTitle(location.pathname)}
            navOpen={navOpen}
            onOpen={() => setOpenedAt(navOpen ? null : location.pathname)}
          />
        )}

        {/* Everything behind an open drawer is unreachable to pointer,
            keyboard and assistive tech alike — the focus trap handles Tab,
            `inert` handles the rest. */}
        <div className="route-slot" inert={navOpen}>
          {/* A panel at the page's own height, so the split chunk landing does
              not collapse the layout and bounce it back. */}
          <Suspense fallback={<div className="route-fallback" aria-busy />}>
          {/*
            Route transition.

            `mode="wait"` — the outgoing page finishes leaving before the
            incoming one starts. The alternative, cross-fading them, requires
            stacking both pages absolutely for the overlap, and every page here
            is a normal-flow document of unknown height; absolutely positioning
            them collapses the scroll container mid-navigation and the page
            jumps. Sequential is the correct trade, and it is only affordable
            because the exit is 80ms of opacity with no movement.

            `initial={false}` suppresses the enter animation on first paint, so
            a cold load renders the first screen immediately rather than fading
            it in after the bundle has already made the user wait.

            Keyed on `pathname` so it fires per screen — not on search or hash
            changes, which are the same screen filtering itself.
          */}
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={location.pathname}
              variants={routeTransition}
              initial="hidden"
              animate="visible"
              exit="exit"
            >
              {/* `location` is pinned to the key so the outgoing page keeps
                  rendering its own route while it animates out, instead of
                  instantly re-rendering as the new route and fading that. */}
              <Routes location={location}>
                <Route path="/"             element={<Landing />}       />
                <Route path="/dashboard"    element={<Dashboard />}     />
                <Route path="/build"        element={<NewBuild />}      />
                <Route path="/build/:id"    element={<BuildProgress />} />
                <Route path="/projects/:id" element={<ProjectDetail />} />
                <Route path="/stats"        element={<Statistics />}    />
              </Routes>
            </motion.div>
          </AnimatePresence>
          </Suspense>
        </div>
      </main>

      <FloatingStatus />
    </div>
  );
}
