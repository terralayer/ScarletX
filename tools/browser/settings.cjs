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
const calendar = titles.map((title, i) => ({title, date: `2026-09-${20 + i}`, monitored:true}));
let recentCount = 5, upcomingCount = 5, stressTitles = false;

async function route(request) {
  const url = new URL(request.request().url());
  assert.equal(url.hostname, 'scarletx.test', 'No external requests in the screenshot fixture');
  const pathname = url.pathname;
  if (pathname.includes('/artwork/') || pathname.endsWith('/screengrab') || pathname.endsWith('/stream')) return request.fulfill({status:404,body:''});
  if (pathname.startsWith('/api/')) {
    if(request.request().method() !== 'GET'){ if(failWrites)return request.fulfill({status:500,json:{detail:'Sample save failure'}}); writes.push({path:pathname,body:request.request().postDataJSON()}); return request.fulfill({json:{}}); }
    let data;
    if (pathname === '/api/system/status') data = {version, performers: 24, studios: 8};
    else if (pathname === '/api/system/diskspace') data = [{exists: true, total_bytes: 4 * 1024 ** 4, used_bytes: 1024 ** 4}];
    else if (pathname === '/api/dashboard/scenes') data = {items: scenes.slice(0, recentCount), total: recentCount};
    else if (pathname === '/api/calendar') data = calendar.slice(0, upcomingCount).map((item, i) => ({...item, title: stressTitles && i === 1 ? longTitle : item.title}));
    else if (pathname === '/api/activity/count') data = {count: 0};
    else if (pathname === '/api/activity/queue') data = {tracked: [], clients: {}};
    else if (pathname === '/api/library/scenes/page') data = {items: scenes, total: scenes.length, has_more: false, next_cursor: null};
    else data = extraFixture(pathname);
    if (pathname === '/api/system/status') data = {...data, database: 'SQLite', media_files: 5};
    if (pathname === '/api/system/diskspace') data = data.map(x => ({...x, name:'Scenes',path:'/media',free_bytes:3*1024**4}));
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

const people = ['Alex Morgan','Jordan Taylor','Casey Lane','Riley Brooks'].map((name,i)=>({id:i+1,tpdb_id:`person-${i}`,name,monitored:true,bio:'Fictional sample profile for this interface preview.',status:'Active',career_start_year:2020}));
const studios = ['Example Studio','Northlight Films','Coastal Pictures'].map((name,i)=>({id:i+1,tpdb_id:`studio-${i}`,name,monitored:true,description:'Fictional studio used to preview library management.',scene_count:12,downloaded_scene_count:5}));
const files = scenes.map((s,i)=>({id:i+1,scene_id:i+1,scene_title:s.title,studio:s.studio,release_date:s.release_date,size_bytes:2147483648,duration_seconds:2700,width:1920,height:1080,video_codec:'H.264',container:'MP4',path:`/media/${s.title}.mp4`,display_name:s.title,play_count:0,position_seconds:0}));
const settingsFixture = {
 general:{app_name:'ScarletX',log_level:'INFO'},theporndb:{configured:false,base_url:'https://api.theporndb.net'},
 newznab_indexers:[],native_usenet:{enabled:true,max_connections:32,incomplete_dir:'/downloads/incomplete',complete_dir:'/downloads/completed',max_retries:2,speed_limit_mb_s:0,repair_enabled:true,unpack_enabled:true,providers:[],tools:{sabctools:true,par2:true,unrar:true,'7z':true}},
 file_management:{enabled:true,import_mode:'move',scene_naming_template:'{studio}/{title} ({release_date})',recycle_bin_path:'/media/.recycle',minimum_free_space_gb:10},
 automation:{enabled:true,interval_minutes:30,batch_size:25},rss:{enabled:true,interval_minutes:15,max_releases_per_indexer:100,max_grabs_per_cycle:10},
 backups:{enabled:true,directory:'/backups',interval_hours:24,keep:7},security:{ui_auth_enabled:false,api_key_enabled:false,api_key_configured:false}
};
function extraFixture(p) {
 if(p==='/api/settings')return settingsFixture;
 if(p==='/api/root-folders')return [{id:1,name:'Scenes',path:'/media',is_default:true}];
 if(p==='/api/system/health')return {status:'ok'};
 if(p==='/api/library/performers/page')return {items:people,total:people.length};
 if(p==='/api/library/studios/page')return {items:studios,total:studios.length};
 if(/\/performers\/[^/]+\/detail$/.test(p))return people[0];
 if(/\/studios\/[^/]+\/detail$/.test(p))return studios[0];
 if(/\/scenes\/[^/]+\/detail$/.test(p))return {...scenes[0],description:'Fictional library entry for the ScarletX interface preview.',duration:2700,files:[]};
 if(/\/(performers|studios)\/[^/]+\/scenes$/.test(p))return {items:scenes,total:5,per_page:100};
 if(p.startsWith('/api/search/'))return {items:scenes};
 if(p==='/api/activity/page')return {items:[],tracked:[],total:0};
 if(p==='/api/downloads/completed')return {scarletx:[{...files[0],completed_at:'2026-09-17',imported_at:'2026-09-17',total_bytes:2147483648}],total:1};
 if(p==='/api/downloads/failed')return {scarletx:[],total:0};
 if(p==='/api/history/page')return {items:[{event_type:'import',message:'Autumn Light imported into the library.',created_at:'2026-09-17'}],total:1,event_counts:{import:1}};
 if(p==='/api/media-library/status')return {files:5,total_bytes:10737418240,missing:0,duplicate_groups:0,unmatched:0,tools:{ffmpeg:true,ffprobe:true}};
 if(p==='/api/media-library/files/page')return {items:files,total:5,has_more:false};
 if(p==='/api/media-library/duplicates'||p==='/api/media-library/unmatched')return [];
 if(p==='/api/media-library/health')return {counts:{total:0},issues:[]};
 if(p==='/api/wanted/missing')return scenes.slice(0,3).map(s=>({...s,library_item_id:s.id}));
 if(/\/media-files\/\d+\/detail/.test(p))return files[0];
 if(p.endsWith('/playback'))return {};
 throw Error('Unhandled fixture '+p);
}

const writes=[];
let failWrites=false;
(async()=>{
 const browser=await chromium.launch({headless:true});
 try {
 const page=await browser.newPage({viewport:{width:1440,height:1100}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route);await page.goto('http://scarletx.test');
 await page.waitForSelector('#stats .dashboard-stat');
 assert.equal(await page.locator('[data-approved-nav="discover"]').count(),0);
 await page.locator('[data-approved-nav="indexers"]').click();await page.waitForSelector('#addIndexer');
 await page.evaluate(async()=>{view='scenes';await renderEntities('scenes')});
 await page.locator('[data-mode="search"]').click();
 assert.equal(await page.locator('[data-mode="search"]').getAttribute('class'),'active');

 for(const width of [1440,768,390]){
 await page.setViewportSize({width,height:1100});
 for(const tab of ['general','metadata','indexers','downloads','media','automation','backups','security','system']){
 await page.evaluate(async tab=>{view='settings';settingsTab=tab;await settings()},tab);
 await page.waitForSelector('.settings-section');
 if(width===390)assert.ok((await page.locator('.settings-page-heading').boundingBox()).y<400,'Settings should be visible without a viewport of empty sidebar');
 assert.equal(await page.locator('.settings-nav button.active').count(),1);
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${tab} overflow at ${width}`);
 }
 }
 await page.evaluate(async()=>{settingsTab='downloads';await settings()});
 await page.locator('#nativeConnections').fill('48');
 await page.locator('#nativeEnabledToggle').uncheck();
 await page.locator('#addProvider').click();
 await page.locator('[data-p=host]').fill('news.example.test');
 await page.locator('#saveNative').click();
 await page.waitForSelector('#nativeEnabledToggle');
 assert.equal(writes.at(-1).body.max_connections,48);
 assert.equal(writes.at(-1).body.enabled,false);
 assert.equal(writes.at(-1).body.providers[0].password,null);
 await page.locator('#nativeConnections').fill('60');
 const count=writes.length;await page.locator('#resetSettings').click();
 await page.waitForFunction(()=>document.querySelector('#nativeConnections')?.value==='32');
 assert.equal(writes.length,count);
 await page.evaluate(async()=>{settingsTab='indexers';await settings()});
 assert.equal(await page.locator('.indexer').count(),0);
 await page.locator('#addIndexer').click();
 await page.locator('[data-k=name]').fill('Example');await page.locator('[data-k=url]').fill('https://example.test');
 await page.locator('#saveIndexers').click();
 assert.equal(writes.at(-1).body.indexers[0].api_key,null);
 for(const [tab,button,paths] of [
 ['general','saveGeneral',['/api/settings/general']],['metadata','saveTPDB',['/api/settings/theporndb']],
 ['automation','saveAuto',['/api/settings/automation','/api/settings/rss']],
 ['backups','saveBackup',['/api/settings/backups']],
 ['media','saveMedia',['/api/settings/file-management','/api/settings/file-management/advanced','/api/root-folders/1']]]){
 await page.evaluate(async tab=>{settingsTab=tab;await settings()},tab);
 const before=writes.length;await page.locator('#'+button).click();
 await page.waitForFunction(id=>!document.querySelector('#'+id)?.disabled,button);
 assert.deepEqual(writes.slice(before).map(w=>w.path),paths);
 }
 await page.evaluate(async()=>{settingsTab='general';await settings()});
 await page.locator('#appName').fill('Keep my edit');failWrites=true;
 await page.locator('#saveGeneral').click();
 await page.waitForFunction(()=>!document.querySelector('#saveGeneral').disabled);
 assert.equal(await page.locator('#appName').inputValue(),'Keep my edit');failWrites=false;
 // Save captures all values and prevents Reset during a multi-request update.
 await page.evaluate(async()=>{settingsTab='automation';await settings()});
 await page.locator('#autoInterval').fill('60');await page.locator('#rssInterval').fill('120');
 let releaseSave,saveStarted;
 const saveStart=new Promise(resolve=>saveStarted=resolve),saveHold=new Promise(resolve=>releaseSave=resolve);
 await page.route('**/api/settings/automation',async request=>{saveStarted();await saveHold;await route(request)});
 await page.locator('#saveAuto').click();await saveStart;
 assert.equal(await page.locator('#resetSettings').isDisabled(),true);
 // Even if a field changes during the request, the clicked Save uses its snapshot.
 await page.locator('#rssInterval').fill('15');releaseSave();
 await page.waitForFunction(()=>!document.querySelector('#saveAuto')?.disabled);
 assert.equal(writes.at(-1).path,'/api/settings/rss');assert.equal(writes.at(-1).body.interval_minutes,120);
 await page.unroute('**/api/settings/automation');
 // A slow system request must not write into another tab or raise an exception.
 let releaseHealth,healthStarted;
 const started=new Promise(resolve=>healthStarted=resolve);
 const hold=new Promise(resolve=>releaseHealth=resolve);
 await page.route('**/api/system/health',async request=>{healthStarted();await hold;await request.fulfill({json:{status:'ok'}})});
 await page.evaluate(()=>{settingsTab='system';void settings()});await started;
 await page.evaluate(async()=>{settingsTab='general';await settings()});
 releaseHealth();await page.waitForTimeout(50);
 assert.equal(await page.locator('#appName').count(),1);
 assert.equal(await page.locator('.settings-page-heading h2').textContent(),'General');
 await page.unroute('**/api/system/health');
 // Security validation still blocks mismatched passwords before any write.
 await page.evaluate(async()=>{settingsTab='security';await settings()});
 await page.locator('#uiAuthEnabledToggle').check();
 await page.locator('#securityPassword').fill('sample-password-123');
 await page.locator('#securityPasswordConfirm').fill('different-password-123');
 const securityBefore=writes.length;await page.locator('#saveSecurity').click();
 assert.equal(writes.length,securityBefore);
 await page.locator('#securityPasswordConfirm').fill('sample-password-123');
 await page.locator('#saveSecurity').click();await page.waitForSelector('#stats .dashboard-stat');
 assert.equal(writes.at(-1).path,'/api/settings/security');
 assert.equal(writes.at(-1).body.ui_auth_enabled,true);
 assert.deepEqual(errors,[]);
 console.log('Settings: nine tabs at three widths, all save flows, failure retention, save/reset race, delayed navigation, and Discover removal passed.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
