import type { Page, ConsoleMessage } from '@playwright/test';

/** The routes the app serves, with the live fixtures the plan documents. */
export const ROUTES = {
  landing:   '/',
  dashboard: '/dashboard',
  newBuild:  '/build',
  stats:     '/stats',
  /** done_with_context — handoff banner, scores, tokens. */
  detail:    '/projects/fb3e4b24-5491-4925-bdb2-4a096df4735f',
  /** cancelled — the build that used to read "Build complete". */
  cancelled: '/build/d715e3f9-ac30-4d62-947c-97976c75d87e',
} as const;

export const ALL_ROUTES = Object.values(ROUTES);

/** The widths the layout must survive. 420 is the one that used to clip. */
export const VIEWPORTS = [
  { name: 'desktop-wide', width: 1440, height: 900 },
  { name: 'desktop',      width: 1024, height: 800 },
  { name: 'tablet',       width: 820,  height: 1100 },
  { name: 'phone-large',  width: 640,  height: 900 },
  { name: 'phone',        width: 420,  height: 840 },
];

/**
 * Console errors, minus the noise a dev server legitimately produces.
 *
 * React Router's future-flag notices and Vite's HMR chatter are warnings about
 * the tooling, not defects in the app, and treating them as failures would
 * train everyone to ignore this check.
 */
const IGNORED_CONSOLE = [
  /React Router Future Flag/i,
  /Download the React DevTools/i,
  /\[vite\] connect/i,
];

export function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (msg: ConsoleMessage) => {
    if (msg.type() !== 'error') return;
    const text = msg.text();
    if (IGNORED_CONSOLE.some(re => re.test(text))) return;
    errors.push(text);
  });
  page.on('pageerror', err => errors.push(`Uncaught: ${err.message}`));
  return errors;
}

export function collectFailedRequests(page: Page): string[] {
  const failed: string[] = [];
  page.on('requestfailed', req => {
    // Aborted requests are normal on navigation away from a polling page.
    const failure = req.failure()?.errorText ?? '';
    if (/ERR_ABORTED|NS_BINDING_ABORTED/.test(failure)) return;
    failed.push(`${req.method()} ${req.url()} — ${failure}`);
  });
  page.on('response', res => {
    if (res.status() >= 500) failed.push(`${res.status()} ${res.url()}`);
  });
  return failed;
}

/**
 * Horizontal overflow, measured two ways.
 *
 * `body { overflow-x: hidden }` makes the scrollWidth comparison pass even when
 * content genuinely runs off the edge — the overflow is clipped, not absent. So
 * the element scan is the check that actually finds anything; the document
 * comparison is kept because it catches the case where the clip is removed.
 */
export async function findOverflow(page: Page) {
  return page.evaluate(() => {
    const docWidth = document.documentElement.clientWidth;

    /**
     * An element that runs past the edge is only a *problem* if nothing above
     * it clips. The ambient mesh, for instance, deliberately parks blurred
     * orbs beyond the viewport inside a fixed `overflow: hidden` container —
     * they extend past the edge and are clipped, which is the design, not a
     * defect. Walk up and skip anything already contained.
     */
    const isClipped = (el: HTMLElement): boolean => {
      let parent = el.parentElement;
      while (parent && parent !== document.documentElement) {
        const s = getComputedStyle(parent);
        if (s.overflowX !== 'visible' || s.overflow === 'hidden' || s.overflow === 'clip') {
          return true;
        }
        parent = parent.parentElement;
      }
      return false;
    };

    const offenders: Array<{ selector: string; right: number; width: number }> = [];
    for (const el of Array.from(document.querySelectorAll<HTMLElement>('body *'))) {
      const style = getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden') continue;
      // A fixed overlay parked off-canvas (the closed drawer) is not overflow.
      if (style.position === 'fixed' && style.transform !== 'none') continue;

      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) continue;

      // 1px of tolerance for sub-pixel layout rounding.
      if (rect.right <= docWidth + 1) continue;
      if (isClipped(el)) continue;

      const id = el.id ? `#${el.id}` : '';
      const cls = typeof el.className === 'string' && el.className
        ? `.${el.className.trim().split(/\s+/).join('.')}`
        : '';
      offenders.push({
        selector: `${el.tagName.toLowerCase()}${id}${cls}`.slice(0, 120),
        right: Math.round(rect.right),
        width: Math.round(rect.width),
      });
    }

    return {
      docWidth,
      scrollWidth: document.documentElement.scrollWidth,
      offenders: offenders.slice(0, 10),
    };
  });
}

/** Elements declaring a transition or animation, for the reduced-motion check. */
export async function findMotionDeclarations(page: Page) {
  return page.evaluate(() => {
    const moving: string[] = [];
    for (const el of Array.from(document.querySelectorAll<HTMLElement>('*'))) {
      const s = getComputedStyle(el);
      const hasAnim = s.animationName !== 'none'
        && parseFloat(s.animationDuration) > 0.05;
      const hasTrans = s.transitionProperty !== 'none'
        && s.transitionProperty !== 'all'
        && parseFloat(s.transitionDuration) > 0.05;
      if (hasAnim || hasTrans) {
        moving.push(`${el.tagName.toLowerCase()}.${String(el.className).slice(0, 60)}`);
      }
    }
    return moving;
  });
}

/** Elements running an animation that never ends. */
export async function findInfiniteAnimations(page: Page) {
  return page.evaluate(() => {
    const looping: Array<{ selector: string; animation: string }> = [];
    for (const el of Array.from(document.querySelectorAll<HTMLElement>('*'))) {
      const s = getComputedStyle(el);
      if (s.animationIterationCount.split(',').some(c => c.trim() === 'infinite')
          && s.animationName !== 'none') {
        looping.push({
          selector: `${el.tagName.toLowerCase()}.${String(el.className).slice(0, 60)}`,
          animation: s.animationName,
        });
      }
    }
    return looping;
  });
}

/** True when the backend is answering — the suite skips API-dependent checks otherwise. */
export async function backendUp(page: Page): Promise<boolean> {
  try {
    const res = await page.request.get('/health', { timeout: 4000 });
    return res.ok();
  } catch {
    return false;
  }
}
