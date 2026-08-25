import { useSyncExternalStore } from 'react';

/**
 * useMediaQuery — subscribe to a CSS media query from React.
 *
 * Built on useSyncExternalStore rather than useEffect + useState so there is no
 * first-paint flash of the wrong branch and no setState-in-effect: the store
 * *is* the media query list.
 *
 * The app uses one breakpoint in JS — the 900px point where the sidebar stops
 * being a column and becomes a drawer. CSS owns every other breakpoint;
 * this exists because the drawer's focus trap and `inert` cannot be expressed
 * in a stylesheet.
 */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mql = window.matchMedia(query);
      mql.addEventListener('change', onChange);
      return () => mql.removeEventListener('change', onChange);
    },
    () => window.matchMedia(query).matches,
    // Server/prerender fallback: assume the desktop column, which is the
    // layout the markup already describes.
    () => false,
  );
}
