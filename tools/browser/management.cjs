const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
const {route}=require('./settings.cjs');
const fixture=require('./management-fixtures.cjs');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route);
  let failConnection=false,failSchedule=false,revision='fixture-1',schedule=fixture('/api/operations/download-schedule');
  await page.route('**/api/operations/**',async request=>{
   const r=request.request(),u=new URL(r.url());requests.push({path:u.pathname,method:r.method(),body:r.postDataJSON()});
   if(u.pathname==='/api/operations/download-schedule'&&r.method()==='PATCH'){
    if(failSchedule)return request.fulfill({status:500,json:{detail:'Storage temporarily unavailable'}});
    schedule={rule:r.postDataJSON(),state:{active:false}};return request.fulfill({json:schedule});
   }
   if(failConnection&&u.pathname.endsWith('/test'))return request.fulfill({status:502,json:{detail:'Connection test failed'}});
   let data=fixture(u.pathname);
   if(u.pathname==='/api/operations/download-schedule')data=schedule;
   if(u.pathname==='/api/operations/connections')data.steps.forEach(step=>step.revision=revision);
   if(u.pathname.endsWith('/test'))data.revision=revision;
   if(u.pathname==='/api/operations/backup-reminder')data={...data,state:'overdue',message:'Your scheduled backup is overdue.'};
   return request.fulfill({json:data});
  });
  await page.goto('http://scarletx.test');await page.waitForSelector('.backup-reminder');
  await page.locator('.backup-reminder button').click();await page.waitForSelector('#backupNow');
  await page.waitForFunction(()=>document.querySelector('.management-body')?.textContent.includes('overdue'));
  await page.evaluate(async()=>{settingsTab='general';await settings()});await page.waitForSelector('#connectionWizard');
  for(const id of ['metadata','indexers','downloads']){await page.locator(`[data-test-connection=${id}]`).click();await page.waitForFunction(id=>document.querySelector(`[data-test-connection=${id}]`)?.closest('article').textContent.includes('Connection tested'),id)}
  assert.match(await page.locator('#connectionWizard h3').textContent(),/Complete/);
  failConnection=true;await page.locator('[data-test-connection=indexers]').click();
  await page.waitForFunction(()=>document.querySelector('[data-test-connection=indexers]').closest('article').textContent.includes('Connection test failed'));
  assert.equal(await page.evaluate(()=>JSON.parse(sessionStorage.getItem('scarletxConnectionChecks')).indexers),undefined);
  failConnection=false;
  revision='fixture-2';await page.evaluate(async()=>{await settings()});await page.waitForSelector('#connectionWizard');
  assert.doesNotMatch(await page.locator('#connectionWizard h3').textContent(),/Complete/);
  await page.locator('[data-configure=downloads]').click();await page.waitForSelector('#downloadScheduleForm');
  await page.selectOption('#scheduleEnabled','true');await page.fill('#scheduleTimezone','America/Los_Angeles');await page.selectOption('#scheduleMode','limit');await page.fill('#scheduleSpeed','3');
  failSchedule=true;await page.locator('#downloadScheduleForm [type=submit]').click();await page.waitForFunction(()=>document.querySelector('#scheduleResult').textContent.includes('unavailable'));
  assert.equal(await page.inputValue('#scheduleSpeed'),'3');failSchedule=false;
  await page.locator('#downloadScheduleForm [type=submit]').click();await page.waitForFunction(()=>document.querySelector('#scheduleResult').textContent==='Schedule saved.');
  assert.equal(schedule.rule.timezone,'America/Los_Angeles');assert.equal(schedule.rule.speed_limit_mb_s,3);
  const out=path.resolve(__dirname,'../../../../outputs/scarletx-truenas-submission/management-preview');fs.mkdirSync(out,{recursive:true});
  for(const width of [1440,390]){
   await page.setViewportSize({width,height:1050});
   for(const tab of ['general','downloads','system','backups']){
    await page.evaluate(async tab=>{settingsTab=tab;await settings()},tab);
    await page.waitForSelector(tab==='system'?'.management-storage-card':tab==='downloads'?'#downloadScheduleForm':tab==='general'?'#connectionWizard':'.management-body .state');
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${tab} overflow at ${width}`);
    await page.screenshot({path:path.join(out,`${tab}-${width}.png`),fullPage:true});
   }
  }
  await page.evaluate(async()=>{view='library';await mediaLibrary()});await page.locator('#openCleanup').click();await page.waitForSelector('[data-cleanup-category]');
  const before=requests.length;for(const category of ['missing','unmatched','duplicates']){await page.locator(`[data-cleanup-category=${category}]`).click();await page.waitForSelector('[data-cleanup-next]')}
  assert.ok(requests.slice(before).every(r=>r.method==='GET'));
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:path.join(out,'cleanup-390.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: management panels desktop/mobile, wizard tests and revision reset, schedule save/failure retention, backup reminder, read-only cleanup');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
