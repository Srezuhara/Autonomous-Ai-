import { test, expect, type Page } from '@playwright/test';
import { ROUTES, collectConsoleErrors } from './helpers';

/**
 * motion.spec.ts — the animations, verified as behaviour rather than as markup.
 *
 * `layout.spec.ts` already guards the two motion *rules* (nothing loops;
 * reduced motion turns everything off). This file checks the opposite thing:
 * that the motion which is supposed to be there actually runs, and that the
 * elements it moves end up where the static layout says they belong.
 *
 * Every assertion here is written against something observable — a measured
 * box, a computed transform, a settled opacity — because "the component
 * renders" is exactly the check that keeps passing while an animation is
 * silently broken.
 */

/** The bounding box of a selector, or null when it is not in the DOM. */
async function boxOf(page: Page, selector: string) {
  const el = page.locator(selector);
  return (await el.count()) ? el.first().boundingBox() : null;
}

test.describe('route transitions', () => {
  test('the incoming page settles fully opaque and untransformed', async ({ page }) => {
    await page.goto(ROUTES.dashboard);
    await page.waitForLoadState('networkidle');

    await page.getByRole('link', { name: /statistics/i }).click();

    // The route wrapper is the element <AnimatePresence> owns; Framer writes
    // opacity and transform onto it inline.
    const wrapper = page.locator('.route-slot > div').first();
    await expect(wrapper).toBeVisible();

    // A stuck `opacity: 0.34` or a leftover `translateY` is the classic
    // symptom of an interrupted presence animation, and it is completely
    // invisible to a test that only asserts the page rendered.
    await expect
      .poll(async () => wrapper.evaluate(el => getComputedStyle(el).opacity), { timeout: 4000 })
      .toBe('1');

    const transform = await wrapper.evaluate(el => getComputedStyle(el).transform);
    expect(['none', 'matrix(1, 0, 0, 1, 0, 0)']).toContain(transform);
  });

  test('the outgoing page is unmounted, not left underneath', async ({ page }) => {
    // `mode="wait"` must leave exactly one route wrapper mounted once the
    // navigation has settled. Two means an exit never completed and the app is
    // silently rendering the previous screen below the current one.
    await page.goto(ROUTES.dashboard);
    await page.waitForLoadState('networkidle');

    await page.getByRole('link', { name: /statistics/i }).click();
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    await expect.poll(async () => page.locator('.route-slot > div').count()).toBe(1);
  });
});

test.describe('the shared filter chip', () => {
  test('one tint travels between chips rather than one existing per chip', async ({ page }) => {
    await page.goto(ROUTES.dashboard);
    await page.waitForLoadState('networkidle');

    const tint = page.locator('.chip__active');
    await expect(tint).toHaveCount(1);

    const before = await tint.boundingBox();
    expect(before).not.toBeNull();

    await page.getByRole('button', { name: 'Done', exact: true }).click();

    // Still exactly one node — it moved, it was not replaced.
    await expect(tint).toHaveCount(1);

    await expect
      .poll(async () => {
        const b = await tint.boundingBox();
        return b ? Math.round(b.x) : -1;
      }, { timeout: 4000 })
      .not.toBe(Math.round(before!.x));

    // It has to land *on* the pressed chip, not somewhere between the two —
    // this is what catches a layout animation that animates but never
    // reconciles with its final position.
    //
    // Polled to settlement rather than sampled once. The rail is a spring, and
    // a spring's duration is a function of how much CPU the machine has left;
    // under a loaded parallel run it is still travelling several hundred
    // milliseconds after the position has begun to change. Sampling once here
    // asserts on a mid-flight frame and fails by a pixel or two at random,
    // which is worse than no test at all.
    const chip = page.locator('.chip[aria-pressed="true"]');
    await expect
      .poll(async () => {
        const chipBox = await chip.boundingBox();
        const tintBox = await tint.boundingBox();
        if (!chipBox || !tintBox) return Number.MAX_SAFE_INTEGER;
        return Math.max(
          Math.abs(tintBox.x - chipBox.x),
          Math.abs(tintBox.width - chipBox.width),
        );
      }, { timeout: 4000 })
      .toBeLessThan(2);
  });
});

test.describe('the sidebar rail', () => {
  test('a single rail moves to the active route', async ({ page }) => {
    await page.goto(ROUTES.dashboard);
    await page.waitForLoadState('networkidle');

    const rail = page.locator('.navlink__rail');
    await expect(rail).toHaveCount(1);

    const started = await rail.boundingBox();

    await page.getByRole('link', { name: /statistics/i }).click();
    await expect(rail).toHaveCount(1);

    await expect
      .poll(async () => {
        const b = await rail.boundingBox();
        return b ? Math.round(b.y) : -1;
      }, { timeout: 4000 })
      .not.toBe(Math.round(started!.y));

    // It must end up inside the active link's own vertical extent — a rail
    // parked beside the wrong item is worse than no rail at all.
    const linkBox = await page.locator('.navlink--active').boundingBox();
    const railBox = await rail.boundingBox();
    expect(railBox!.y).toBeGreaterThanOrEqual(linkBox!.y - 1);
    expect(railBox!.y + railBox!.height).toBeLessThanOrEqual(linkBox!.y + linkBox!.height + 1);
  });
});

test.describe('the pipeline meter', () => {
  test('is driven by transform and settles on its announced value', async ({ page }) => {
    await page.goto(ROUTES.cancelled);
    await page.waitForLoadState('networkidle');

    const fill = page.locator('.steptrack__fill');
    await expect(fill).toBeVisible();

    const bar = page.locator('[role="progressbar"][aria-label="Pipeline progress"]');
    const reported = Number(await bar.getAttribute('aria-valuenow'));

    // scaleX, never width: animating width would relayout the panel on every
    // frame of a build that runs for minutes. The fill therefore stays at the
    // track's full width at all times.
    const fillWidth = await fill.evaluate(el => getComputedStyle(el).width);
    const trackWidth = await bar.evaluate(el => getComputedStyle(el).width);
    expect(fillWidth).toBe(trackWidth);

    // The scale must settle on the value the progressbar reports to assistive
    // tech. If the two disagree, the seen progress and the announced progress
    // are telling the user different things.
    await expect
      .poll(async () => {
        const m = await fill.evaluate(el => getComputedStyle(el).transform);
        if (m === 'none') return 100;
        return Math.round(Number(m.match(/matrix\(([-\d.]+)/)?.[1] ?? 1) * 100);
      }, { timeout: 5000 })
      .toBe(reported);
  });
});

test.describe('disclosures', () => {
  test('the step-log accordion opens to content height and closes to nothing', async ({ page }) => {
    await page.goto(ROUTES.detail);
    await page.waitForLoadState('networkidle');

    const toggle = page.getByRole('button', { name: /step logs/i });
    test.skip(!(await toggle.count()), 'this build recorded no step logs');

    await toggle.click();

    const reveal = page.locator('.pd-logs__reveal');
    await expect(reveal).toBeVisible();

    // Settles on the real content height — not on a frozen mid-animation value,
    // and not on a hardcoded max-height that would clip a long log.
    await expect
      .poll(async () => {
        const outer = await reveal.boundingBox();
        const inner = await boxOf(page, '.pd-logs__body');
        if (!outer || !inner) return -1;
        return Math.abs(outer.height - inner.height);
      }, { timeout: 4000 })
      .toBeLessThan(2);

    // And the chevron rotated rather than being swapped for a second glyph.
    const rotation = await page.locator('.pd-disclosure__chev')
      .evaluate(el => getComputedStyle(el).transform);
    expect(rotation).not.toBe('none');

    await toggle.click();
    await expect(reveal).toHaveCount(0);
  });
});

test.describe('reduced motion', () => {
  /*
    `page.emulateMedia()`, not a `test.use({ reducedMotion })` fixture.
    Measured: the fixture form left `matchMedia('(prefers-reduced-motion:
    reduce)')` reporting **false** inside the page, so the suite ran the full
    animations while claiming to test the reduced path — a test that cannot
    fail, guarding the accessibility behaviour it is named after. The explicit
    call is the spelling `layout.spec.ts` already uses, and it is verified
    below rather than assumed.
  */
  test.beforeEach(async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
  });

  test('the emulation is actually in effect', async ({ page }) => {
    await page.goto(ROUTES.dashboard);
    const reduced = await page.evaluate(
      () => matchMedia('(prefers-reduced-motion: reduce)').matches,
    );
    expect(reduced, 'reduced-motion emulation did not reach the page').toBe(true);
  });

  test('the shared chip arrives instantly instead of travelling', async ({ page }) => {
    /*
      A different check from the one in layout.spec.ts, and it has to be: that
      test scans computed CSS for `transition` and `animation` declarations,
      and Framer's motion is neither. It is inline style written per frame from
      JavaScript, so a CSS scan sees a perfectly clean page whether or not the
      animations are still running at full length.

      What disables them is `<MotionConfig reducedMotion="user">` in main.tsx,
      which covers `layoutId` projection as well as the animate props. The
      observable consequence is that the tint is already on the newly pressed
      chip by the time the click returns, instead of springing ~110px into
      place over ~280ms.
    */
    await page.goto(ROUTES.dashboard);
    await page.waitForLoadState('networkidle');

    const tint = page.locator('.chip__active');
    await expect(tint).toHaveCount(1);

    await page.getByRole('button', { name: 'Failed', exact: true }).click();

    const chipBox = await page.locator('.chip[aria-pressed="true"]').boundingBox();
    const tintBox = await tint.boundingBox();
    expect(Math.abs(tintBox!.x - chipBox!.x)).toBeLessThan(2);
  });

  test('a route change lands with no residual opacity or transform', async ({ page }) => {
    await page.goto(ROUTES.dashboard);
    await page.waitForLoadState('networkidle');

    await page.getByRole('link', { name: /statistics/i }).click();
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    const wrapper = page.locator('.route-slot > div').first();
    expect(await wrapper.evaluate(el => getComputedStyle(el).opacity)).toBe('1');

    const transform = await wrapper.evaluate(el => getComputedStyle(el).transform);
    expect(['none', 'matrix(1, 0, 0, 1, 0, 0)']).toContain(transform);
  });
});

test.describe('no motion regressions', () => {
  test('exercising every animated surface produces no console errors', async ({ page }) => {
    const errors = collectConsoleErrors(page);

    // Walk the app the way a user would, so every presence animation in the
    // product is mounted, animated and unmounted at least once. Framer reports
    // layout and presence faults on the console, so a clean walk is real
    // signal here rather than a formality.
    await page.goto(ROUTES.dashboard);
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Running', exact: true }).click();
    await page.getByRole('button', { name: 'Done', exact: true }).click();
    await page.getByRole('button', { name: 'All', exact: true }).click();

    await page.getByRole('link', { name: /statistics/i }).click();
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await page.getByRole('button', { name: '7d', exact: true }).click();
    await page.getByRole('button', { name: '30d', exact: true }).click();

    await page.getByRole('link', { name: /dashboard/i }).click();
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    await page.goto(ROUTES.detail);
    await page.waitForLoadState('networkidle');

    await page.goto(ROUTES.cancelled);
    await page.waitForLoadState('networkidle');

    expect(errors).toEqual([]);
  });
});
