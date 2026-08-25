import { test, expect } from '@playwright/test';
import {
  ROUTES, ALL_ROUTES, VIEWPORTS,
  collectConsoleErrors, collectFailedRequests,
  findOverflow, findMotionDeclarations, findInfiniteAnimations,
} from './helpers';

test.describe('every route loads cleanly', () => {
  for (const [name, path] of Object.entries(ROUTES)) {
    test(`${name} has no console errors or failed requests`, async ({ page }) => {
      const errors = collectConsoleErrors(page);
      const failed = collectFailedRequests(page);

      await page.goto(path);
      await page.waitForLoadState('networkidle');

      expect(errors, `console errors on ${path}`).toEqual([]);
      expect(failed, `failed requests on ${path}`).toEqual([]);
    });
  }
});

test.describe('no horizontal overflow', () => {
  for (const vp of VIEWPORTS) {
    for (const path of ALL_ROUTES) {
      test(`${path} at ${vp.name} (${vp.width}px)`, async ({ page }) => {
        await page.setViewportSize({ width: vp.width, height: vp.height });
        await page.goto(path);
        await page.waitForLoadState('networkidle');

        const result = await findOverflow(page);

        // The element scan is the real check: `overflow-x: hidden` on the body
        // clips the evidence the document-width comparison would rely on.
        expect(
          result.offenders,
          `elements past the right edge at ${vp.width}px on ${path}`
        ).toEqual([]);

        expect(
          result.scrollWidth,
          `document scrolls horizontally at ${vp.width}px on ${path}`
        ).toBeLessThanOrEqual(result.docWidth + 1);
      });
    }
  }
});

test.describe('motion', () => {
  test('nothing loops except the in-flight spinner', async ({ page }) => {
    for (const path of ALL_ROUTES) {
      await page.goto(path);
      await page.waitForLoadState('networkidle');

      const looping = await findInfiniteAnimations(page);
      const unexpected = looping.filter(l => l.animation !== 'spin');

      expect(unexpected, `looping animations on ${path}`).toEqual([]);
    }
  });

  test('reduced motion turns off every transition and animation', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });

    for (const path of ALL_ROUTES) {
      await page.goto(path);
      await page.waitForLoadState('networkidle');

      const moving = await findMotionDeclarations(page);
      expect(moving, `elements still declaring motion on ${path}`).toEqual([]);
    }
  });
});

test.describe('the mobile drawer', () => {
  test.use({ viewport: { width: 420, height: 840 } });

  test('opens, traps focus, and closes on Escape', async ({ page }) => {
    await page.goto(ROUTES.dashboard);

    // Located by `aria-controls`, not by name: the accessible name flips to
    // "Close navigation" once the drawer is open, so a name-based locator
    // stops matching the very element it just clicked.
    const toggle = page.locator('button[aria-controls="app-sidebar"]');
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAccessibleName('Open navigation');
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');

    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');

    const drawer = page.locator('#app-sidebar');
    await expect(drawer).toBeVisible();

    // Focus must land inside and stay there.
    for (let i = 0; i < 8; i++) {
      await page.keyboard.press('Tab');
      const inside = await drawer.evaluate(el => el.contains(document.activeElement));
      expect(inside, 'Tab escaped the drawer').toBe(true);
    }

    await page.keyboard.press('Escape');
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });

  test('content behind the drawer is inert', async ({ page }) => {
    await page.goto(ROUTES.dashboard);
    await page.locator('button[aria-controls="app-sidebar"]').click();

    const inert = await page.locator('.route-slot').evaluate(
      el => (el as HTMLElement).inert === true || el.hasAttribute('inert')
    );
    expect(inert, 'routed content is reachable behind the open drawer').toBe(true);
  });

  test('closes when navigating to another route', async ({ page }) => {
    await page.goto(ROUTES.dashboard);
    await page.locator('button[aria-controls="app-sidebar"]').click();

    await page.locator('#app-sidebar').getByRole('link', { name: 'Statistics' }).click();

    await expect(page).toHaveURL(/\/stats/);
    await expect(page.locator('button[aria-controls="app-sidebar"]'))
      .toHaveAttribute('aria-expanded', 'false');
  });

  test('the scrim fades out rather than vanishing', async ({ page }) => {
    await page.goto(ROUTES.dashboard);
    const scrim = page.locator('.nav-scrim');

    // Mounted whenever the sidebar is a drawer, so it can animate both ways.
    await expect(scrim).toHaveCount(1);
    await expect(scrim).toHaveCSS('opacity', '0');

    await page.locator('button[aria-controls="app-sidebar"]').click();
    await expect(scrim).toHaveCSS('opacity', '1');

    await page.keyboard.press('Escape');
    await expect(scrim).toHaveCSS('opacity', '0');
    // Still in the DOM — deleting it is what made the close snap.
    await expect(scrim).toHaveCount(1);
  });
});

test.describe('keyboard traversal', () => {
  test('every control on the dashboard is reachable with a visible ring', async ({ page }) => {
    await page.goto(ROUTES.dashboard);
    await page.waitForLoadState('networkidle');

    const seen = new Set<string>();
    const ringless: string[] = [];

    for (let i = 0; i < 40; i++) {
      await page.keyboard.press('Tab');
      const info = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el || el === document.body) return null;
        const s = getComputedStyle(el);
        const hasRing =
          (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0)
          || s.boxShadow !== 'none';
        return {
          key: `${el.tagName}:${el.textContent?.trim().slice(0, 30) ?? ''}`,
          hasRing,
        };
      });
      if (!info) continue;
      if (seen.has(info.key)) break; // cycled back to the start
      seen.add(info.key);
      if (!info.hasRing) ringless.push(info.key);
    }

    expect(seen.size, 'nothing was focusable').toBeGreaterThan(3);
    expect(ringless, 'focusable controls with no visible focus indicator').toEqual([]);
  });
});
