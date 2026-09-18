// Test the shipped authentication gate and first-run flow at desktop/mobile sizes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '../..');
(async () => {
 const browser = await chromium.launch({headless:true});
 try {
  for (const width of [390, 1440]) {
   const page = await browser.newPage({viewport:{width,height:900}});
   let complete=false, signedIn=false, generation=0, submitted, fail=false;
   await page.route('http://scarletx.test/**', async route => {
    const p=new URL(route.request().url()).pathname;
    if(p==='/api/auth/status')return route.fulfill({json:{setup_required:!complete,authenticated:signedIn,username:signedIn?'troy':null}});
    if(p==='/api/setup/api-key')return route.fulfill({json:{api_key:(++generation).toString().padStart(43,'x')}});
    if(p==='/api/setup/admin'){
     submitted=route.request().postDataJSON();
     if(fail)return route.fulfill({status:500,json:{detail:'Could not save setup'}});
     complete=true;signedIn=true;return route.fulfill({json:{username:'troy'}});
    }
    if(p==='/api/auth/logout'){signedIn=false;return route.fulfill({status:204});}
    if(p==='/api/auth/login'){
     if(route.request().postDataJSON().password!=='correct-horse-battery')return route.fulfill({status:401,json:{detail:'Invalid username or password'}});
     signedIn=true;return route.fulfill({json:{username:'troy'}});
    }
    if(p==='/scarletx-wordmark.webp'){
     const dir=path.join(root,'frontend');
     const encoded=fs.readdirSync(dir).filter(n=>n.startsWith('scarletx-wordmark.webp.b64.')).sort().map(n=>fs.readFileSync(path.join(dir,n),'utf8')).join('');
     return route.fulfill({contentType:'image/webp',body:Buffer.from(encoded,'base64')});
    }
    if(p==='/api/activity/stream')return route.fulfill({status:404});
    if(p==='/')return route.fulfill({contentType:'text/html',body:`<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="/auth.css"></head><body><script src="/auth.js"></script><main id="content"></main><script>authGateBoot(()=>{document.getElementById('content').textContent=window.scarletxInitialView==='settings'?'Settings':'Dashboard'})</script></body></html>`});
    return route.fulfill({body:fs.readFileSync(path.join(root,'frontend',p)),contentType:p.endsWith('.js')?'text/javascript':'text/css'});
   });
   await page.goto('http://scarletx.test/');
   await page.locator('#authApiKey').waitFor();
   await page.waitForFunction(()=>document.getElementById('authApiKey').value.length===43);
   const first=await page.locator('#authApiKey').inputValue();
   await page.click('#authRefreshKey');
   await page.waitForFunction(v=>document.getElementById('authApiKey').value!==v,first);
   const key=await page.locator('#authApiKey').inputValue();
   assert.equal(await page.locator('#content').textContent(),'');
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   if(process.env.SCARLETX_SCREENSHOT_DIR){fs.mkdirSync(process.env.SCARLETX_SCREENSHOT_DIR,{recursive:true});await page.screenshot({path:path.join(process.env.SCARLETX_SCREENSHOT_DIR,`setup-${width}.png`)});}
   await page.fill('#authUsername','troy');await page.fill('#authPassword','correct-horse-battery');await page.fill('#authPasswordConfirm','does-not-match');
   await page.click('#authSubmit');assert.match(await page.locator('#authError').textContent(),/Passwords do not match/);
   await page.fill('#authPasswordConfirm','correct-horse-battery');fail=true;
   await page.click('#authSubmit');await page.waitForFunction(()=>document.getElementById('authError').textContent==='Could not save setup');
   assert.equal(await page.locator('#authApiKey').inputValue(),key);fail=false;
   await page.click('#authSubmit');await page.waitForFunction(()=>document.getElementById('content').textContent==='Settings');
   assert.equal(submitted.api_key,key);assert.equal(await page.locator('#authApiKey').inputValue(),'');
   await page.click('#authLogoutButton');await page.locator('#authForm').waitFor();
   assert.equal(await page.locator('#authTitle').textContent(),'Sign in to ScarletX');
   assert.equal(await page.locator('#authSetupFields').isVisible(),false);
   await page.fill('#authUsername','troy');await page.fill('#authPassword','wrong');await page.click('#authSubmit');
   await page.waitForFunction(()=>document.getElementById('authError').textContent.includes('Invalid username'));
   await page.fill('#authPassword','correct-horse-battery');await page.click('#authSubmit');await page.waitForFunction(()=>document.getElementById('content').textContent==='Dashboard');
   await page.close();
  }
  console.log('PASS: first-run setup, regenerate, validation, save retry, Settings redirect, logout/login, desktop/mobile');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1)});
