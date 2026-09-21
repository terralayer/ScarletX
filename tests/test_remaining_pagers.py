import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def run_node(script: str, *files: str) -> None:
    result = subprocess.run(
        ["node", "-e", script, *[str(FRONTEND / file) for file in files]],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_active_queue_pager_rolls_back_failure_and_rejects_rapid_clicks():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[2],'utf8');
const section=source.slice(0,source.indexOf('function applyLiveQueue'));
let pending=[],scrolls=0,notices=[];
const button={dataset:{queuePage:'next'},disabled:false,isConnected:true};
const queue={innerHTML:'page one',isConnected:true,querySelectorAll:()=>[button],scrollIntoView:()=>scrolls++};
const badge={textContent:''};
const ctx={
  ACTIVITY_QUEUE_PAGE_SIZE:25,view:'activity',window:{addEventListener(){}},
  $:selector=>selector==='#activityQueue'?queue:selector==='#queueBadge'?badge:null,
  api:url=>new Promise((resolve,reject)=>pending.push({url,resolve,reject})),
  notify:message=>notices.push(message),bytes:String,esc:String,empty:String,
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
vm.runInContext('var activityQueuePage=1;',ctx);
vm.runInContext(section,ctx);
ctx.activityQueueHtml=rows=>rows.map(row=>row.name).join(',');
(async()=>{
  ctx.bindActivityQueuePager(queue,100);
  const first=button.onclick();
  assert.equal(vm.runInContext('activityQueuePage',ctx),2);
  assert.equal(button.disabled,true);
  assert.equal(await button.onclick(),false,'a second click must not issue another request');
  assert.equal(pending.length,1);
  pending.shift().resolve({items:[{name:'page two'}],total:100,page:2});
  assert.equal(await first,true);
  assert.match(queue.innerHTML,/page two/);
  assert.equal(scrolls,1);

  ctx.bindActivityQueuePager(queue,100);
  const failed=button.onclick();
  assert.equal(vm.runInContext('activityQueuePage',ctx),3);
  pending.shift().reject(Error('offline'));
  assert.equal(await failed,false);
  assert.equal(vm.runInContext('activityQueuePage',ctx),2);
  assert.match(queue.innerHTML,/page two/,'failed loads preserve the displayed rows');
  assert.equal(scrolls,1);
  assert.deepEqual(notices,['offline']);
})().catch(error=>{console.error(error);process.exitCode=1});
""",
        "pagination.js",
        "ui_overrides.js",
    )


def test_active_queue_loader_does_not_paint_a_stale_view_or_response():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const section=source.slice(0,source.indexOf('function applyLiveQueue'));
let pending=[];
const queue={innerHTML:'current rows',isConnected:true,querySelectorAll:()=>[]};
const badge={textContent:'7'};
const ctx={
  ACTIVITY_QUEUE_PAGE_SIZE:25,view:'activity',window:{addEventListener(){}},
  $:selector=>selector==='#activityQueue'?queue:selector==='#queueBadge'?badge:null,
  api:()=>new Promise(resolve=>pending.push(resolve)),notify(){},bytes:String,esc:String,empty:String,
};
vm.createContext(ctx);vm.runInContext('var activityQueuePage=1;',ctx);vm.runInContext(section,ctx);
ctx.activityQueueHtml=rows=>rows.map(row=>row.name).join(',');
(async()=>{
  const older=ctx.loadActivityQueuePage(queue);
  const newer=ctx.loadActivityQueuePage(queue);
  pending[1]({items:[{name:'newest'}],total:9,page:1});
  assert.equal(await newer,true);
  pending[0]({items:[{name:'stale'}],total:99,page:1});
  assert.equal(await older,false);
  assert.match(queue.innerHTML,/newest/);
  assert.doesNotMatch(queue.innerHTML,/stale/);
  assert.equal(badge.textContent,9);

  const navigated=ctx.loadActivityQueuePage(queue);
  ctx.view='library';
  pending[2]({items:[{name:'wrong view'}],total:42,page:1});
  assert.equal(await navigated,false);
  assert.doesNotMatch(queue.innerHTML,/wrong view/);
  assert.equal(badge.textContent,9);
})().catch(error=>{console.error(error);process.exitCode=1});
""",
        "ui_overrides.js",
    )


def test_active_queue_event_during_transition_is_coalesced_in_both_response_orders():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[2],'utf8');
const section=source.slice(0,source.indexOf('function mediaFileRowsHtml'));
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function scenario(order){
  let pageRequests=[],countRequests=[],scrolls=0;
  const listeners={};
  const button={dataset:{queuePage:'next'},disabled:false,isConnected:true};
  const queue={
    innerHTML:'page one',isConnected:true,scrollIntoView:()=>scrolls++,
    querySelector:()=>null,insertAdjacentHTML(){},
    querySelectorAll:selector=>selector==='[data-live-job]'?[]:[button],
  };
  const badge={textContent:'100'};
  const ctx={
    ACTIVITY_QUEUE_PAGE_SIZE:25,view:'activity',
    window:{addEventListener:(name,handler)=>listeners[name]=handler},
    $:selector=>selector==='#activityQueue'?queue:selector==='#queueBadge'?badge:null,
    api:url=>new Promise((resolve,reject)=>{
      const request={url,resolve,reject};
      (url==='/api/activity/count'?countRequests:pageRequests).push(request);
    }),
    notify(){},bytes:String,esc:String,empty:String,
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
  vm.runInContext('var activityQueuePage=1;',ctx);
  vm.runInContext(section,ctx);
  ctx.activityQueueHtml=rows=>rows.map(row=>row.name).join(',');

  ctx.applyLiveQueue({tracked:[{external_id:'live',name:'live page one'}]});
  listeners['scarletx:queue-event']({detail:{kind:'snapshot'}});
  assert.equal(countRequests.length,1);
  ctx.bindActivityQueuePager(queue,100);
  const transition=button.onclick();
  assert.equal(pageRequests.length,1);
  assert.equal(vm.runInContext('activityQueuePage',ctx),2);

  if(order==='event-first'){
    countRequests[0].resolve({active:100});await flush();
    assert.equal(pageRequests.length,1,'event refresh must not invalidate the explicit request');
    assert.equal(vm.runInContext('activityQueuePage',ctx),2);
    pageRequests[0].resolve({items:[{name:'explicit page two'}],total:100,page:2});
  }else{
    pageRequests[0].resolve({items:[{name:'explicit page two'}],total:100,page:2});await flush();
    assert.match(queue.innerHTML,/explicit page two/);
    countRequests[0].resolve({active:100});
  }
  await flush();
  const deferredCount=countRequests[1];
  if(deferredCount){deferredCount.resolve({active:100});await flush()}
  const deferredPage=pageRequests[1];
  if(deferredPage){deferredPage.resolve({items:[{name:'fresh page two'}],total:100,page:2});await flush()}
  assert.equal(await transition,true);
  assert.equal(vm.runInContext('activityQueuePage',ctx),2);
  assert.match(queue.innerHTML,/page two/);
  assert.equal(scrolls,1);
}
(async()=>{await scenario('event-first');await scenario('page-first')})()
  .catch(error=>{console.error(error);process.exitCode=1});
""",
        "pagination.js",
        "ui_overrides.js",
    )


def test_active_queue_total_shrink_commits_clamp_only_after_replacement_succeeds():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const section=source.slice(0,source.indexOf('function applyLiveQueue'));
let pending=[];
const queue={innerHTML:'page three rows',isConnected:true,querySelectorAll:()=>[]};
const badge={textContent:'75'};
const ctx={
  ACTIVITY_QUEUE_PAGE_SIZE:25,view:'activity',window:{addEventListener(){}},
  $:selector=>selector==='#activityQueue'?queue:selector==='#queueBadge'?badge:null,
  api:url=>new Promise((resolve,reject)=>pending.push({url,resolve,reject})),
  notify(){},bytes:String,esc:String,empty:String,
};
vm.createContext(ctx);vm.runInContext('var activityQueuePage=3;',ctx);vm.runInContext(section,ctx);
ctx.activityQueueHtml=rows=>rows.map(row=>row.name).join(',');
(async()=>{
  const load=ctx.loadActivityQueuePage(queue);
  pending[0].resolve({items:[],total:30,page:3});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(pending.length,2,'shrunk totals require the new last page before committing');
  assert.match(pending[1].url,/page=2/);
  assert.equal(vm.runInContext('activityQueuePage',ctx),3);
  assert.equal(queue.innerHTML,'page three rows');
  pending[1].reject(Error('replacement offline'));
  await assert.rejects(load,/replacement offline/);
  assert.equal(vm.runInContext('activityQueuePage',ctx),3);
  assert.equal(queue.innerHTML,'page three rows');
  assert.equal(badge.textContent,'75');
})().catch(error=>{console.error(error);process.exitCode=1});
""",
        "ui_overrides.js",
    )


def test_live_snapshot_does_not_repaint_an_explicit_queue_transition():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[2],'utf8');
const section=source.slice(0,source.indexOf('function mediaFileRowsHtml'));
let pageRequests=[],countRequests=[],unhandled=[];
process.on('unhandledRejection',error=>unhandled.push(error));
const listeners={};
const button={dataset:{queuePage:'next'},disabled:false,isConnected:true};
const queue={
  innerHTML:'page one',isConnected:true,scrollIntoView(){},querySelector:()=>null,insertAdjacentHTML(){},
  querySelectorAll:selector=>selector==='[data-live-job]'?[]:[button],
};
const ctx={
  ACTIVITY_QUEUE_PAGE_SIZE:25,view:'activity',window:{addEventListener:(name,handler)=>listeners[name]=handler},
  $:selector=>selector==='#activityQueue'?queue:selector==='#queueBadge'?{textContent:''}:null,
  api:url=>new Promise((resolve,reject)=>(url==='/api/activity/count'?countRequests:pageRequests).push({url,resolve,reject})),
  notify(){},bytes:String,esc:String,empty:String,
};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
vm.runInContext('var activityQueuePage=1;',ctx);vm.runInContext(section,ctx);
ctx.activityQueueHtml=rows=>rows.map(row=>row.name).join(',');
(async()=>{
  ctx.bindActivityQueuePager(queue,100);
  const transition=button.onclick();
  ctx.applyLiveQueue({tracked:[{external_id:'live',name:'live replacement'}]});
  listeners['scarletx:queue-event']({detail:{kind:'snapshot'}});
  assert.equal(queue.innerHTML,'page one');
  assert.equal(countRequests.length,0,'event work is deferred behind the explicit transition');
  assert.equal(pageRequests.length,1);
  pageRequests[0].resolve({items:[{name:'page two'}],total:100,page:2});
  assert.equal(await transition,true);
  assert.equal(vm.runInContext('activityQueuePage',ctx),2);
  assert.match(queue.innerHTML,/page two/);
  assert.equal(countRequests.length,1,'coalesced live refresh starts after the transition');
  countRequests[0].resolve({active:100});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(pageRequests.length,2);
  pageRequests[1].reject(Error('deferred refresh offline'));
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(unhandled,[]);
  assert.match(queue.innerHTML,/page two/);
})().catch(error=>{console.error(error);process.exitCode=1});
""",
        "pagination.js",
        "ui_overrides.js",
    )


def test_media_library_pager_keeps_host_rows_and_ignores_stale_responses():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[2],'utf8');
const section=source.slice(source.indexOf('function mediaFileRowsHtml'));
let pending=[],scrolls=0,notices=[];
const button={dataset:{libraryPage:'next'},disabled:false,isConnected:true};
const files={innerHTML:'page one',isConnected:true,querySelectorAll:()=>[button],scrollIntoView:()=>scrolls++};
const ctx={
  view:'library',MEDIA_LIBRARY_PAGE_SIZE:50,$:selector=>selector==='#libraryFiles'?files:null,
  api:url=>new Promise((resolve,reject)=>pending.push({url,resolve,reject})),
  notify:message=>notices.push(message),bytes:String,esc:String,fmtDate:String,durationText:String,
  empty:String,playMedia(){},openLocalScene(){},post(){},patch(){},confirm:()=>true,setTimeout(){},pageHead(){return ''},
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
vm.runInContext('var mediaLibraryPage=1,mediaLibraryCursors=[null,"cursor-one"],mediaLibraryHasMore=true,mediaLibraryRows=[],mediaLibraryCursor=null,mediaLibraryRequest=0,mediaLibraryPageRequest=0;',ctx);
vm.runInContext(section,ctx);
ctx.mediaFilesHtml=rows=>rows.map(row=>row.name).join(',');
ctx.mediaLibraryPagerHtml=()=>'';
(async()=>{
  ctx.bindMediaLibraryActions(files,150);
  const first=files.onclick({target:{closest:()=>button}});
  assert.equal(await files.onclick({target:{closest:()=>button}}),false,'rapid media clicks share the host lock');
  assert.equal(pending.length,1);
  assert.match(pending[0].url,/cursor=cursor-one/);
  pending.shift().resolve({items:[{name:'page two'}],has_more:true,next_cursor:'cursor-two'});
  assert.equal(await first,true);
  assert.equal(vm.runInContext('mediaLibraryPage',ctx),2);
  assert.equal(files.innerHTML,'page two');
  assert.equal(scrolls,1);

  const failed=files.onclick({target:{closest:()=>button}});
  pending.shift().reject(Error('media offline'));
  assert.equal(await failed,false);
  assert.equal(vm.runInContext('mediaLibraryPage',ctx),2);
  assert.equal(files.innerHTML,'page two');
  assert.equal(scrolls,1);

  const older=ctx.loadMediaLibraryPage(150,files);
  const newer=ctx.loadMediaLibraryPage(150,files);
  pending[1].resolve({items:[{name:'newest'}],has_more:false,next_cursor:null});
  assert.equal(await newer,true);
  pending[0].resolve({items:[{name:'stale'}],has_more:false,next_cursor:null});
  assert.equal(await older,false);
  assert.equal(files.innerHTML,'newest');
  assert.deepEqual(notices,['media offline']);
})().catch(error=>{console.error(error);process.exitCode=1});
""",
        "pagination.js",
        "ui_overrides.js",
    )


def test_wanted_pager_preserves_controls_rows_and_page_on_failure():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let pending=[],scrolls=0,notices=[],appWrites=0;
const previous={disabled:false,isConnected:true};
const next={disabled:false,isConnected:true};
const body={
  innerHTML:'',textContent:'',isConnected:true,scrollIntoView:()=>scrolls++,
  querySelectorAll:selector=>selector.includes('.pager button')?[previous,next]:[],
};
const controls={
  searchWanted:{disabled:false,textContent:'Search Wanted',isConnected:true},
  searchWantedSelected:{disabled:true,isConnected:true},unmonitorWantedSelected:{disabled:true,isConnected:true},
  wantedSelectedCount:{textContent:''},wantedSelectPage:{},wantedPrevious:previous,wantedNext:next,
};
const app={set innerHTML(value){this.value=value;appWrites++},get innerHTML(){return this.value}};
const ctx={
  view:'wanted',wantedPage:0,wantedRequest:0,WANTED_PAGE_SIZE:2,
  $:selector=>selector==='#app'?app:selector==='#wantedBody'?body:controls[selector.slice(1)]||null,
  $$:()=>[],api:url=>{
    if(url.startsWith('/api/wanted/missing'))return new Promise((resolve,reject)=>pending.push({url,resolve,reject}));
    throw Error(url);
  },
  pageHead:()=>'',post:()=>({method:'POST'}),notify:message=>notices.push(message),
  esc:String,fmtDate:String,empty:String,
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
(async()=>{
  const initial=ctx.wanted();
  pending.shift().resolve([
    {library_item_id:1,title:'first',release_date:'2026-01-01'},
    {library_item_id:2,title:'second',release_date:'2026-01-02'},
    {library_item_id:3,title:'more',release_date:'2026-01-03'},
  ]);
  assert.equal(await initial,true);
  const firstHtml=body.innerHTML;
  assert.match(firstHtml,/first/);
  assert.equal(appWrites,1);

  const pageTwo=next.onclick();
  assert.equal(await next.onclick(),false,'rapid wanted clicks share the host lock');
  assert.equal(appWrites,1,'paging keeps the page header and bulk controls mounted');
  pending.shift().resolve([
    {library_item_id:4,title:'third',release_date:'2026-01-04'},
    {library_item_id:5,title:'fourth',release_date:'2026-01-05'},
    {library_item_id:6,title:'more',release_date:'2026-01-06'},
  ]);
  assert.equal(await pageTwo,true);
  assert.equal(ctx.wantedPage,1);
  assert.match(body.innerHTML,/third/);
  assert.equal(scrolls,1);

  const failed=next.onclick();
  pending.shift().reject(Error('wanted offline'));
  assert.equal(await failed,false);
  assert.equal(ctx.wantedPage,1);
  assert.match(body.innerHTML,/third/);
  assert.doesNotMatch(body.innerHTML,/<b>first<\/b>/);
  assert.equal(scrolls,1);
  assert.equal(appWrites,1);
  assert.deepEqual(notices,['wanted offline']);
})().catch(error=>{console.error(error);process.exitCode=1});
""",
        "pagination.js",
        "wanted_bulk_overrides.js",
    )


def test_wanted_loader_ignores_older_and_detached_hosts():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let pending=[],renderCount=0;
const makeBody=value=>({innerHTML:value,textContent:'',isConnected:true,querySelectorAll:()=>[]});
const oldBody=makeBody('old'),newBody=makeBody('new'),thirdBody=makeBody('third');
const bodies=[oldBody,newBody,thirdBody];
let currentBody=null;
const controls={
  searchWanted:{isConnected:true},searchWantedSelected:{},unmonitorWantedSelected:{},
  wantedSelectedCount:{},wantedSelectPage:{},wantedPrevious:{},wantedNext:{},
};
const app={set innerHTML(_value){currentBody=bodies[renderCount++];if(renderCount>1)bodies[renderCount-2].isConnected=false}};
const ctx={
  view:'wanted',wantedPage:0,wantedRequest:0,WANTED_PAGE_SIZE:2,
  $:selector=>selector==='#app'?app:selector==='#wantedBody'?currentBody:controls[selector.slice(1)]||null,$$:()=>[],
  api:()=>new Promise(resolve=>pending.push(resolve)),pageHead:()=>'',post:()=>({}),notify(){},
  esc:String,fmtDate:String,empty:String,
};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
(async()=>{
  const older=ctx.wanted();
  const newer=ctx.wanted();
  pending[1]([{library_item_id:2,title:'newest',release_date:'2026-01-02'}]);
  assert.equal(await newer,true);
  pending[0]([{library_item_id:1,title:'stale',release_date:'2026-01-01'}]);
  assert.equal(await older,false);
  assert.match(newBody.innerHTML,/newest/);
  assert.doesNotMatch(oldBody.innerHTML,/stale/);

  ctx.view='wanted';
  const detached=ctx.wanted();
  ctx.view='library';
  pending[2]([{library_item_id:3,title:'wrong host',release_date:'2026-01-03'}]);
  assert.equal(await detached,false);
  assert.doesNotMatch(thirdBody.innerHTML,/wrong host/);
  assert.match(newBody.innerHTML,/newest/);
})().catch(error=>{console.error(error);process.exitCode=1});
""",
        "wanted_bulk_overrides.js",
    )


def test_wanted_empty_page_fallback_rolls_back_when_replacement_fails():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let missing=[],search=[];
const body={innerHTML:'',textContent:'',isConnected:true,querySelectorAll:()=>[]};
const controls={
  searchWanted:{disabled:false,textContent:'Search Wanted',isConnected:true},
  searchWantedSelected:{},unmonitorWantedSelected:{},wantedSelectedCount:{},wantedSelectPage:{},
  wantedPrevious:{},wantedNext:{},
};
const ctx={
  view:'wanted',wantedPage:2,wantedRequest:0,WANTED_PAGE_SIZE:2,
  $:selector=>selector==='#app'?{}:selector==='#wantedBody'?body:controls[selector.slice(1)]||null,
  $$:()=>[],pageHead:()=>'',post:()=>({method:'POST'}),notify(){},esc:String,fmtDate:String,empty:String,
  api:url=>new Promise((resolve,reject)=>{
    const request={url,resolve,reject};
    (url.startsWith('/api/wanted/missing')?missing:search).push(request);
  }),
};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
(async()=>{
  const initial=ctx.wanted();
  missing[0].resolve([{library_item_id:8,title:'page three',release_date:'2026-01-08'}]);
  assert.equal(await initial,true);
  assert.match(body.innerHTML,/page three/);

  const refresh=controls.searchWanted.onclick();
  search[0].resolve({checked:1,queued:0});await new Promise(resolve=>setImmediate(resolve));
  missing[1].resolve([]);await new Promise(resolve=>setImmediate(resolve));
  assert.equal(missing.length,3);
  assert.match(missing[2].url,/offset=0/);
  assert.equal(ctx.wantedPage,2,'fallback page is not committed while replacement is pending');
  assert.match(body.innerHTML,/page three/);
  missing[2].reject(Error('replacement offline'));
  await refresh;
  assert.equal(ctx.wantedPage,2);
  assert.match(body.innerHTML,/page three/);
})().catch(error=>{console.error(error);process.exitCode=1});
""",
        "wanted_bulk_overrides.js",
    )
