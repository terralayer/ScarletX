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
let queueRequests=0, holdQueue=null, holdWanted=null, wantedCount=123;

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
    else if (pathname === '/api/activity/queue') {queueRequests++;if(holdQueue)await holdQueue;data = {tracked: [], clients: {}};}
    else if (pathname === '/api/wanted/missing') {
      const wait=holdWanted;if(wait)await wait;
      const start=Number(url.searchParams.get('offset')||0),limit=Number(url.searchParams.get('limit'));
      data=Array.from({length:Math.max(0,Math.min(limit,wantedCount-start))},(_,i)=>({library_item_id:start+i+1,title:`Wanted ${start+i+1}`,release_date:'2026-01-01'}));
    }
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

(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage();await page.route('http://scarletx.test/**',route);await page.goto('http://scarletx.test/');
  await page.locator('.dashboard-stat').first().waitFor();
  if(!process.argv.includes('--polling')){
   await page.evaluate(()=>{view='wanted';wantedPage=0;render()});await page.locator('#wantedNext').waitFor();
   assert.equal(await page.locator('#wantedBody tbody tr').count(),50);
   assert.equal(await page.locator('#wantedPrevious').isDisabled(),true);
   await page.check('#wantedSelectPage');assert.equal(await page.locator('[data-wanted-select]:checked').count(),25);
   assert.equal(await page.locator('#searchWantedSelected').isDisabled(),false);
   await page.click('#wantedNext');await page.waitForFunction(()=>document.querySelector('#wantedBody tbody tr')?.textContent.includes('Wanted 51'));
   assert.equal(await page.locator('#wantedBody tbody tr').count(),50);
   assert.equal(await page.locator('[data-wanted-select]:checked').count(),0);
   await page.click('#wantedNext');await page.waitForFunction(()=>document.querySelector('#wantedBody tbody tr')?.textContent.includes('Wanted 101'));
   assert.equal(await page.locator('#wantedBody tbody tr').count(),23);assert.equal(await page.locator('#wantedNext').isDisabled(),true);
   await page.click('#wantedPrevious');await page.waitForFunction(()=>document.querySelector('#wantedBody tbody tr')?.textContent.includes('Wanted 51'));
   wantedCount=0;await page.click('#wantedPrevious');await page.waitForFunction(()=>document.querySelector('#wantedBody')?.textContent.includes('Nothing is wanted'));
   wantedCount=123;
   let release;holdWanted=new Promise(resolve=>release=resolve);
   await page.evaluate(()=>{view='wanted';wantedPage=0;render()});
   await page.waitForTimeout(30);
   await page.click('#nav [data-view="dashboard"]');holdWanted=null;
   await page.evaluate(()=>{view='wanted';wantedPage=0;render()});await page.locator('#wantedNext').waitFor();
   await page.click('#wantedNext');await page.waitForFunction(()=>document.querySelector('#wantedBody tbody tr')?.textContent.includes('Wanted 51'));
   release();await page.waitForTimeout(50);
   assert.match(await page.locator('#wantedBody tbody tr').first().textContent(),/Wanted 51/);
  }
  await page.clock.install();
  await page.evaluate(()=>{window.testHidden=false;Object.defineProperty(document,'hidden',{configurable:true,get:()=>window.testHidden});});
  const visibility=async hidden=>page.evaluate(value=>{window.testHidden=value;document.dispatchEvent(new Event('visibilitychange'));},hidden);
  queueRequests=0;
  await page.evaluate(()=>window.dispatchEvent(new Event('scarletx:queue-stream-fallback')));
  await visibility(true);await page.clock.runFor(45000);await new Promise(resolve=>setTimeout(resolve,50));assert.equal(queueRequests,0,'hidden tabs must not poll');
  await Promise.all([page.waitForResponse(r=>r.url().includes('/api/activity/queue')),visibility(false)]);assert.equal(queueRequests,1);
  await page.evaluate(()=>window.dispatchEvent(new Event('scarletx:queue-stream-healthy')));
  await visibility(true);await visibility(false);await page.clock.runFor(45000);await new Promise(resolve=>setTimeout(resolve,50));assert.equal(queueRequests,1,'healthy stream must not resume polling');
  let release;holdQueue=new Promise(resolve=>release=resolve);
  await page.evaluate(()=>window.dispatchEvent(new Event('scarletx:queue-stream-fallback')));
  await page.clock.runFor(15001);await new Promise(resolve=>setTimeout(resolve,50));assert.equal(queueRequests,2);
  await page.evaluate(()=>window.dispatchEvent(new Event('scarletx:queue-stream-healthy')));
  release();holdQueue=null;await page.waitForTimeout(30);await page.clock.runFor(45000);await new Promise(resolve=>setTimeout(resolve,50));
  assert.equal(queueRequests,2,'in-flight poll must not rearm after stream recovers');
  await page.close();console.log('PASS: Wanted pagination, stale navigation, hidden-tab polling, stream recovery race');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1)});
