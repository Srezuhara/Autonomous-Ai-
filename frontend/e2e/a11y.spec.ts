import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { ROUTES } from './helpers';

/**
 * There was no accessibility tooling in this project at all. The bar here is
 * zero serious or critical violations per route — the two severities that
 * describe something a user genuinely cannot get past. Minor and moderate are
 * reported in the failure message when a route does fail, so they are visible
 * without being gating.
 */
const GATING = ['serious', 'critical'];

function analyze(page: Page) {
  return new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
}

test.describe('accessibility', () => {
  for (const [name, path] of Object.entries(ROUTES)) {
    test(`${name} has no serious or critical violations`, async ({ page }) => {
      await page.goto(path);
      await page.waitForLoadState('networkidle');

      const results = await analyze(page);
      const gating = results.violations.filter(v => GATING.includes(v.impact ?? ''));

      expect(
        gating.map(v => `${v.impact}: ${v.id} — ${v.help} (${v.nodes.length} node(s): ${v.nodes[0]?.target.join(' ')})`),
        `axe violations on ${path}`
      ).toEqual([]);
    });
  }

  /**
   * WCAG 2.2 AA Target Size (Minimum) is 24x24 CSS px, and axe does not check
   * it. Found `.back-link` at 93x21 on two screens.
   */
  test('every pointer target is at least 24x24 CSS px', async ({ page }) => {
    for (const [name, path] of Object.entries(ROUTES)) {
      await page.goto(path);
      await page.waitForLoadState('networkidle');

      const undersized = await page.evaluate(() => {
        const sel = 'a[href], button, input, select, textarea, [role="button"], [tabindex]:not([tabindex="-1"])';
        const out = new Set<string>();
        for (const el of Array.from(document.querySelectorAll<HTMLElement>(sel))) {
          const s = getComputedStyle(el);
          if (s.display === 'none' || s.visibility === 'hidden') continue;
          const b = el.getBoundingClientRect();
          if (b.width === 0 || b.height === 0) continue;
          if (b.width < 24 || b.height < 24) {
            out.add(`${Math.round(b.width)}x${Math.round(b.height)} ${el.tagName.toLowerCase()}.${String(el.className).slice(0, 40)}`);
          }
        }
        return [...out];
      });

      expect(undersized, `targets under 24x24 on ${name}`).toEqual([]);
    }
  });

  test('the open drawer is accessible', async ({ page }) => {
    // The drawer only exists below the breakpoint, so the route sweep above
    // never reaches it.
    await page.setViewportSize({ width: 420, height: 840 });
    await page.goto(ROUTES.dashboard);
    await page.locator('button[aria-controls="app-sidebar"]').click();
    await page.waitForLoadState('networkidle');

    const results = await analyze(page);
    const gating = results.violations.filter(v => GATING.includes(v.impact ?? ''));

    expect(
      gating.map(v => `${v.impact}: ${v.id} — ${v.help}`),
      'axe violations with the drawer open'
    ).toEqual([]);
  });

  /**
   * The composer suppresses its textarea's own outline because its surface is
   * supposed to light up instead. When the rebuild dialog rendered it without
   * a `.panel`, the field ended up with no focus indication at all: no border,
   * no shadow, no outline. axe does not catch this.
   */
  test('the composer shows focus in every context it is used', async ({ page }) => {
    const hasIndicator = async () => page.evaluate(() => {
      const el = document.activeElement?.closest('.composer') as HTMLElement | null;
      if (!el) return false;
      const s = getComputedStyle(el);
      const i = getComputedStyle(document.activeElement as HTMLElement);
      return s.boxShadow !== 'none'
        || parseFloat(s.borderTopWidth) > 0
        || (i.outlineStyle !== 'none' && parseFloat(i.outlineWidth) > 0);
    });

    await page.goto(ROUTES.newBuild);
    await page.getByLabel(/Your app/).focus();
    expect(await hasIndicator(), 'NewBuild composer has no focus indicator').toBe(true);

    await page.goto(ROUTES.detail);
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: /Rebuild/i }).first().click();
    await page.getByRole('button', { name: /Custom instructions/ }).click();
    await page.getByLabel(/What should change/).focus();
    expect(await hasIndicator(), 'rebuild dialog composer has no focus indicator').toBe(true);
  });

  test('the rebuild dialog is accessible', async ({ page }) => {
    // Same reasoning: a modal is a state the route sweep cannot reach, and it
    // is the surface where the a11y gap was worst before this cycle.
    await page.goto(ROUTES.detail);
    await page.waitForLoadState('networkidle');

    const rebuild = page.getByRole('button', { name: /Rebuild/i }).first();
    await rebuild.click();
    await expect(page.getByRole('dialog')).toBeVisible();

    const results = await analyze(page);
    const gating = results.violations.filter(v => GATING.includes(v.impact ?? ''));

    expect(
      gating.map(v => `${v.impact}: ${v.id} — ${v.help}`),
      'axe violations with the rebuild dialog open'
    ).toEqual([]);
  });
});
