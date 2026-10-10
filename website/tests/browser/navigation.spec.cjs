const {test, expect} = require('@playwright/test');

for (const mode of ['enabled', 'disabled', 'blocked']) {
  test.describe(`JavaScript ${mode}`, () => {
    test.use({javaScriptEnabled: mode !== 'disabled'});
    test.beforeEach(async ({page}) => {
      if (mode === 'blocked') await page.route('**/assets/*.js', route => route.abort());
    });
    for (const width of [390, 1280]) {
      test(`archived section clicks retain the document at ${width}px`, async ({page}) => {
        await page.setViewportSize({width, height: 900});
        await page.goto('/daily/2026-10-07/');
        await expect(page.locator('main h1')).toBeVisible();
        // The editorial redesign renamed the section shortcut nav to .jump-nav;
        // every on-page jump link must resolve to an element and keep the document.
        const links = page.locator('.jump-nav a');
        const fragments = await links.evaluateAll(nodes => nodes.map(n => n.getAttribute('href')));
        expect(fragments.length).toBeGreaterThan(0);
        expect(fragments.filter(f => f.startsWith('#band-')).length).toBeGreaterThan(0);
        for (const fragment of fragments) {
          expect(fragment).toMatch(/^#[^#]+$/);
          await page.locator(`.jump-nav a[href="${fragment}"]`).click();
          await expect(page).toHaveURL(`http://127.0.0.1:8874/daily/2026-10-07/${fragment}`);
          await expect(page.locator(fragment)).toBeInViewport();
        }
      });
    }
    for (const path of ['/', '/daily/', '/daily/2026-10-07/', '/technology/', '/latest/', '/archive/']) {
      test(`skip link focuses the current main region on ${path}`, async ({page}) => {
        await page.goto(path);
        const skip = page.getByRole('link', {name: 'Skip to content'});
        await expect(skip).toHaveAttribute('href', '#main');
        await skip.focus();
        await skip.press('Enter');
        await expect(page.locator('main#main')).toBeFocused();
        expect(new URL(page.url()).pathname).toBe(path);
        if (mode !== 'enabled') expect(new URL(page.url()).hash).toBe('#main');
      });
    }
  });
}
