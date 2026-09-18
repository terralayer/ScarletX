// Exercise the shipped frontend with fictional API fixtures, without a live server.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '../..');
const frontend = path.join(root, 'frontend');
const version = fs.readFileSync(path.join(root, 'pyproject.toml'), 'utf8').match(/^version = "([^"]+)"/m)[1];
const titles = ['Autumn Light', 'City After Dark', 'A Quiet Morning', 'Coastal Weekend', 'The Long Way Home'];
const scenes = titles.map((title, i) => ({
  id: i + 1, tpdb_id: `demo-${i}`, title, studio: 'Example Studio',
  release_date: `2026-09-${16 - i}`, monitored: true, has_file: true, media_id: i + 1,
  performers: [{id: 'example', name: 'Example Performer'}],
}));
const longTitle = 'A very long upcoming title that wraps onto multiple lines and exposes the row sizing mismatch on desktop';
const calendar = titles.map((title, i) => ({title, date: `2026-09-${20 + i}`}));
let recentCount = 5, upcomingCount = 5, stressTitles = true;

async function route(request) {
  const url = new URL(request.request().url());
  assert.equal(url.hostname, 'scarletx.test', 'No external requests in the screenshot fixture');
  const pathname = url.pathname;
  if (pathname.startsWith('/api/operations/')) return request.fulfill({json:require('./management-fixtures.cjs')(pathname)});
  if (pathname.startsWith('/api/')) {
    let data;
    if (pathname === '/api/system/status') data = {version, performers: 24, studios: 8};
    else if (pathname === '/api/system/diskspace') data = [{exists: true, total_bytes: 4 * 1024 ** 4, used_bytes: 1024 ** 4}];
    else if (pathname === '/api/dashboard/scenes') data = {items: scenes.slice(0, recentCount), total: recentCount};
    else if (pathname === '/api/calendar') data = calendar.slice(0, upcomingCount).map((item, i) => ({...item, title: stressTitles && i === 1 ? longTitle : item.title}));
    else if (pathname === '/api/activity/count') data = {count: 0};
    else if (pathname === '/api/activity/queue') data = {tracked: [], clients: {}};
    else if (pathname === '/api/library/scenes/page') data = {items: scenes, total: scenes.length, has_more: false, next_cursor: null};
    else throw new Error(`Unexpected API request: ${pathname}`);
    return request.fulfill({json: data});
  }
  // Dockerfile.web assembles these exact approved assets from base64 chunks.
  if (['/scarletx-wordmark.webp', '/scarletx-banner.webp'].includes(pathname)) {
    const prefix = pathname === '/scarletx-banner.webp' ? 'scarletx-banner.b64.' : 'scarletx-wordmark.webp.b64.';
    const encoded = fs.readdirSync(frontend).filter(name => name.startsWith(prefix)).sort()
      .map(name => fs.readFileSync(path.join(frontend, name), 'utf8')).join('');
    return request.fulfill({contentType: 'image/webp', body: Buffer.from(encoded, 'base64')});
  }
  const file = path.join(frontend, pathname === '/' ? 'index.html' : pathname);
  const types = {'.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml', '.webp': 'image/webp'};
  return request.fulfill({body: fs.readFileSync(file), contentType: types[path.extname(file)]});
}

async function geometry(page) {
  return page.evaluate(() => {
    const boxes = selector => [...document.querySelectorAll(selector)].map(element => {
      const rect = element.getBoundingClientRect();
      return {top: rect.top, bottom: rect.bottom, height: rect.height};
    });
    return {
      panels: boxes('.approved-dashboard-grid > .panel'),
      headers: boxes('.approved-dashboard-grid .panel-head'),
      recent: boxes('.approved-recent-row'),
      upcoming: boxes('.approved-upcoming .row'),
      overflow: document.documentElement.scrollWidth - innerWidth,
    };
  });
}

(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}, locale: 'en-US', timezoneId: 'UTC', reducedMotion: 'reduce'});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route);
    await page.goto('http://scarletx.test/');
    await page.waitForSelector('.approved-recent-row');
    assert.equal(await page.locator('.approved-upcoming .row b').nth(1).getAttribute('title'), longTitle, 'Full Upcoming title remains available on hover');
    let checks = 0;
    for (const [recent, upcoming] of [[5, 5], [2, 5], [5, 2], [0, 0], [0, 5], [5, 0]]) {
      recentCount = recent;
      upcomingCount = upcoming;
      await page.evaluate(() => dashboard());
      for (const width of [1920, 1440, 1100, 981, 980, 680, 390]) {
        await page.setViewportSize({width, height: 1000});
        const layout = await geometry(page);
        const label = `${width}px, ${recent} recent / ${upcoming} upcoming`;
        const equal = (a, b, detail) => assert.ok(Math.abs(a - b) < 0.5, `${label}: ${detail} (${a} vs ${b})`);
        assert.equal(layout.overflow, 0, `${label}: horizontal overflow`);
        assert.equal(layout.recent.length, recent);
        assert.equal(layout.upcoming.length, upcoming || 1);
        if (width > 980) {
          equal(layout.panels[0].top, layout.panels[1].top, 'panel tops');
          equal(layout.panels[0].bottom, layout.panels[1].bottom, 'panel bottoms');
          equal(layout.headers[0].bottom, layout.headers[1].bottom, 'header baselines');
          for (let i = 0; i < Math.min(recent, upcoming); i++) {
            equal(layout.recent[i].top, layout.upcoming[i].top, `row ${i + 1} top`);
            equal(layout.recent[i].height, layout.upcoming[i].height, `row ${i + 1} height`);
          }
        } else {
          assert.ok(layout.panels[1].top >= layout.panels[0].bottom, `${label}: stacked panels overlap`);
        }
        checks++;
      }
    }
    assert.deepEqual(errors, [], 'Browser JavaScript errors');
    console.log(`PASS: ${checks} dashboard layouts (long titles, unequal counts, empty states, desktop/tablet/mobile)`);
    if (process.argv.includes('--screenshots')) {
      recentCount = upcomingCount = 5;
      stressTitles = false;
      await page.setViewportSize({width: 1440, height: 1000});
      await page.evaluate(() => dashboard());
      await page.evaluate(() => Promise.all([...document.images].map(image => image.decode().catch(() => {}))));
      await page.evaluate(async () => { const image = new Image(); image.src = '/scarletx-banner.webp'; await image.decode(); window.scrollTo(0, 0); });
      await page.screenshot({path: path.join(root, 'docs/images/scarletx-dashboard.png'), fullPage: true});
      await page.locator('#nav [data-view="scenes"]').click();
      await page.waitForSelector('#entityGrid tbody tr');
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({path: path.join(root, 'docs/images/scarletx-scenes.png'), fullPage: true});
      assert.deepEqual(errors, [], 'Screenshot JavaScript errors');
      console.log('Updated both README screenshots using fictional sample data.');
    }
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
