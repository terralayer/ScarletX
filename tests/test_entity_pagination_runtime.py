import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "frontend" / "app.js"
NAVIGATION = ROOT / "frontend" / "navigation_error_overrides.js"


def run_node(script: str, *paths: Path) -> None:
    script = script.replace('vm.createContext(ctx);', '''vm.createContext(ctx);
if(!('view' in ctx))ctx.view='performers';
vm.runInContext(fs.readFileSync(require('path').join(require('path').dirname(process.argv[1]),'pagination.js'),'utf8'),ctx);''')
    result = subprocess.run(
        ["node", "-e", script, *(str(path) for path in paths)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_runtime_loader_records_page_cursor_and_uses_it_for_the_next_page():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const grid={};
const urls=[],painted=[];
const responses=[
  {items:[{id:'first'}],total:40,has_more:true,next_cursor:'cursor-one'},
  {items:[{id:'second'}],total:null,has_more:false,next_cursor:null},
];
const ctx={
  render(){},renderEntities(){},view:'performers',
  entityLibraryQuery:{performers:''},entityPrefetch:new Map(),
  entityPage:{performers:1},entityPageCursors:{performers:[null]},
  $:selector=>selector==='#entityGrid'?grid:null,
  entityPageUrl:(type,cursor)=>cursor?`/page?cursor=${cursor}`:'/page',
  api:async url=>{urls.push(url);return responses.shift()},
  paintEntityLibrary:(type,data)=>painted.push(data.items[0].id),
  prefetchEntityPage(){},notify(){},
};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
(async()=>{
  await ctx.loadEntityLibrary('performers');
  assert.equal(ctx.entityPageCursors.performers[1],'cursor-one');
  ctx.entityPage.performers=2;
  await ctx.loadEntityLibrary('performers',ctx.entityPageCursors.performers[1]);
  assert.deepEqual(urls,['/page','/page?cursor=cursor-one']);
  assert.deepEqual(painted,['first','second']);
})().catch(error=>{console.error(error);process.exitCode=1});
""",
        NAVIGATION,
    )


def test_returning_to_an_entity_list_refreshes_the_visible_page():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const section=source.slice(source.indexOf('async function renderEntities'),source.indexOf('function entityPager'));
const app={},grid={innerHTML:''},pageSize={};
const loaded=[],painted=[];
const ctx={
  entityMode:{performers:'library'},entityLibraryFilter:{performers:'all'},
  entityPageSize:{performers:25},entityLibraryCache:{performers:{items:[{id:'page-two'}]}},
  entityCursors:{performers:null},entityTotals:{performers:40},
  entityPage:{performers:2},entityPageCursors:{performers:[null,'cursor-one']},
  entityPrefetch:new Map(),
  $:selector=>selector==='#app'?app:selector==='#entityGrid'?grid:selector==='#entityPageSize'?pageSize:null,
  $$:()=>[],pageHead:()=>'',empty:value=>value,
  paintEntityLibrary:(type,data)=>painted.push(data.items[0].id),
  loadEntityLibrary:async(type,cursor)=>loaded.push(cursor),
};
vm.createContext(ctx);vm.runInContext(section,ctx);
(async()=>{
  await ctx.renderEntities('performers');
  assert.deepEqual(painted,['page-two']);
  assert.deepEqual(loaded,['cursor-one']);
})().catch(error=>{console.error(error);process.exitCode=1});
""",
        APP,
    )


def test_entity_navigation_after_search_reopens_the_saved_library():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const section=source.slice(source.indexOf('async function renderEntities'),source.indexOf('function entityPager'));
for(const type of ['performers','studios','scenes']){
  const app={},grid={innerHTML:''},pageSize={},loaded=[],searches=[];
  const ctx={
    entityMode:{[type]:'search'},entityLibraryFilter:{[type]:'all'},
    entityPageSize:{[type]:25},entityLibraryCache:{[type]:null},
    entityCursors:{[type]:null},entityTotals:{[type]:null},
    entityPage:{[type]:1},entityPageCursors:{[type]:[null]},entityPrefetch:new Map(),
    $:selector=>selector==='#app'?app:selector==='#entityGrid'?grid:selector==='#entityPageSize'?pageSize:null,
    $$:()=>[],pageHead:()=>'',empty:value=>value,
    loadEntityLibrary:async(kind,cursor)=>{loaded.push([kind,cursor]);grid.innerHTML='Saved library cards'},
    searchEntity:async(kind,query)=>{searches.push([kind,query]);grid.innerHTML='Search cards'},
  };
  vm.createContext(ctx);vm.runInContext(section,ctx);
  ctx.renderEntities(type);
  assert.deepEqual(loaded,[[type,null]],'sidebar/back navigation must fetch the library after a search');
  assert.equal(grid.innerHTML,'Saved library cards');
  assert.equal(ctx.entityMode[type],'library');
  ctx.renderEntities(type,'Alexis');
  assert.deepEqual(searches,[[type,'Alexis']],'an explicit search must still open search results');
  assert.equal(ctx.entityMode[type],'search');
}
""",
        APP,
    )


def test_cursor_pages_keep_the_first_page_total_and_pager():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const section=source.slice(source.indexOf('function entityPager'),source.indexOf('function entityPageUrl'));
const grid={
  innerHTML:'',appended:'',
  querySelector:()=>null,querySelectorAll:()=>[],
  insertAdjacentHTML(position,html){this.appended+=html},
};
const ctx={
  entityPage:{performers:1},entityPageSize:{performers:25},
  entityPageCursors:{performers:[null]},entityLibraryCache:{performers:null},
  entityCursors:{performers:null},entityTotals:{performers:null},
  $:selector=>selector==='#entityGrid'?grid:null,
  entityCard:(type,row)=>`<article>${row.id}</article>`,bindEntityActions(){},
};
vm.createContext(ctx);vm.runInContext(section,ctx);
const rows=prefix=>Array.from({length:25},(_,index)=>({id:`${prefix}-${index}`}));
ctx.paintEntityLibrary('performers',{items:rows('first'),total:60,has_more:true,next_cursor:'cursor-one'});
ctx.entityPage.performers=2;grid.appended='';
ctx.paintEntityLibrary('performers',{items:rows('second'),total:null,has_more:true,next_cursor:'cursor-two'});
assert.equal(ctx.entityLibraryCache.performers.total,60);
assert.match(grid.appended,/data-entity-page="prev"/);
assert.match(grid.appended,/data-entity-page="next"/);
""",
        APP,
    )


def test_entity_pages_render_pagination_above_and_below_results():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const section=source.slice(source.indexOf('function entityPager'),source.indexOf('function entityPageUrl'));
const top={innerHTML:'',querySelectorAll:()=>[]};
const grid={appended:'',querySelector:()=>null,querySelectorAll:()=>[],insertAdjacentHTML(position,html){this.appended+=html}};
const ctx={
  entityPage:{performers:1},entityPageSize:{performers:25},entityPageCursors:{performers:[null]},
  entityLibraryCache:{performers:null},entityCursors:{performers:null},entityTotals:{performers:null},
  $:selector=>selector==='#entityPaginationTop'?top:selector==='#entityGrid'?grid:null,
  entityCard:(type,row)=>`<article>${row.id}</article>`,bindEntityActions(){},
};
vm.createContext(ctx);vm.runInContext(section,ctx);
ctx.paintEntityLibrary('performers',{items:[{id:'one'}],total:26,has_more:true,next_cursor:'cursor-one'});
assert.match(top.innerHTML,/data-entity-page="next"/,'top pagination should be rendered');
assert.match(grid.appended,/data-entity-page="next"/,'bottom pagination should remain rendered');
""",
        APP,
    )


def test_pager_is_available_when_cursor_response_has_no_total():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const section=source.slice(source.indexOf('function entityPager'),source.indexOf('function bindEntityPager'));
const ctx={entityPage:{performers:1},entityPageSize:{performers:25}};
vm.createContext(ctx);vm.runInContext(section,ctx);
const html=ctx.entityPager('performers',null,true);
assert.match(html,/data-entity-page="next"/);
""",
        APP,
    )


def test_previous_next_and_numbered_buttons_use_the_target_page_cursor():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const section=source.slice(source.indexOf('function bindEntityPager'),source.indexOf('function paintEntityLibrary'));
const button={dataset:{}},grid={querySelectorAll:()=>[button]};
const calls=[];
const ctx={
  entityPage:{performers:1},entityPageCursors:{performers:[null,'cursor-one','cursor-two']},
  $:selector=>selector==='#entityGrid'?grid:null,
  loadEntityLibrary:async(type,cursor)=>{calls.push([ctx.entityPage[type],cursor]);return true},
};
vm.createContext(ctx);vm.runInContext(section,ctx);
async function click(action,start,hasMore=true){
  button.dataset.entityPage=action;ctx.entityPage.performers=start;
  ctx.bindEntityPager('performers',{has_more:hasMore});await button.onclick();
}
(async()=>{
await click('prev',3);
await click('next',2);
await click('1',3);
await click('2',3);
assert.deepEqual(calls,[[2,'cursor-one'],[3,'cursor-two'],[1,null],[2,'cursor-one']]);
})().catch(error=>{console.error(error);process.exitCode=1});
""",
        APP,
    )


def test_successful_page_change_scrolls_to_top_but_failed_or_stale_page_does_not():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const section=source.slice(source.indexOf('function bindEntityPager'),source.indexOf('function paintEntityLibrary'));
const button={dataset:{entityPage:'next'},disabled:false};
const grid={querySelectorAll:()=>[button]},app={scrollIntoView:()=>scrolls++};
let finish,scrolls=0;
const ctx={
  entityPage:{performers:1},entityPageCursors:{performers:[null,'page-two']},
  $:selector=>selector==='#entityGrid'?grid:selector==='#app'?app:null,
  loadEntityLibrary:()=>new Promise(resolve=>finish=resolve),
};
vm.createContext(ctx);vm.runInContext(section,ctx);
(async()=>{
  for(const [outcome,expected] of [[true,1],[false,1],[undefined,1]]){
    ctx.entityPage.performers=1;button.disabled=false;
    ctx.bindEntityPager('performers',{has_more:true});
    const task=button.onclick();
    assert.equal(scrolls,expected-(outcome===true?1:0),'do not scroll before loading finishes');
    finish(outcome);await task;
    assert.equal(scrolls,expected,'only a successfully displayed page should scroll');
  }
})().catch(error=>{console.error(error);process.exitCode=1});
""",
        APP,
    )


def test_download_queue_page_scrolls_to_its_start_only_after_successful_load():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const section=source.slice(source.indexOf('function bindActivityQueuePager'),source.indexOf('function applyLiveQueue'));
const button={dataset:{queuePage:'next'}};
let finish,fail,scrolls=0;
const el={querySelectorAll:()=>[button],scrollIntoView:()=>scrolls++};
const ctx={ACTIVITY_QUEUE_PAGE_SIZE:25,activityQueuePage:1,view:'activity',
  activityQueueTransition:null,activityQueueRefreshPending:false,activityQueuePendingSnapshot:null,
  $:selector=>selector==='#activityQueue'?el:null,notify(){},
  loadActivityQueuePage:()=>new Promise((resolve,reject)=>{finish=resolve;fail=reject}),
};
vm.createContext(ctx);vm.runInContext(section,ctx);
(async()=>{
  ctx.bindActivityQueuePager(el,100);
  let task=button.onclick();assert.equal(scrolls,0);finish(true);await task;
  assert.equal(ctx.activityQueuePage,2);assert.equal(scrolls,1);
  task=button.onclick();fail(new Error('offline'));await task;assert.equal(scrolls,1);
})().catch(error=>{console.error(error);process.exitCode=1});
""",
        ROOT / 'frontend' / 'ui_overrides.js',
    )


def test_stale_page_response_cannot_overwrite_current_cursor_or_content():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const grid={},pending=[],painted=[];
const defer=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve}};
const ctx={
  render(){},renderEntities(){},view:'performers',
  entityLibraryQuery:{performers:''},entityPrefetch:new Map(),
  entityPage:{performers:2},entityPageCursors:{performers:[null,'cursor-one']},
  $:selector=>selector==='#entityGrid'?grid:null,
  entityPageUrl:(type,cursor)=>cursor?`/page?cursor=${cursor}`:'/page',
  api:()=>{const request=defer();pending.push(request);return request.promise},
  paintEntityLibrary:(type,data)=>painted.push(data.items[0].id),
  prefetchEntityPage(){},notify(){},
};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
(async()=>{
  const stale=ctx.loadEntityLibrary('performers','cursor-one');
  ctx.entityPage.performers=1;
  const current=ctx.loadEntityLibrary('performers',null);
  pending[1].resolve({items:[{id:'current'}],has_more:true,next_cursor:'fresh-cursor'});
  await current;
  pending[0].resolve({items:[{id:'stale'}],has_more:true,next_cursor:'stale-cursor'});
  await stale;
  assert.equal(ctx.entityPageCursors.performers[1],'fresh-cursor');
  assert.equal(ctx.entityPageCursors.performers[2],undefined);
  assert.deepEqual(painted,['current']);
})().catch(error=>{console.error(error);process.exitCode=1});
""",
        NAVIGATION,
    )


def test_filter_change_resets_page_cursor_cache_and_total():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const section=source.slice(source.indexOf('async function renderEntities'),source.indexOf('function entityPager'));
const app={},grid={innerHTML:''},pageSize={},filter={dataset:{libraryFilter:'female'}};
const ctx={
  entityMode:{performers:'library'},entityLibraryFilter:{performers:'all'},
  entityPageSize:{performers:25},entityLibraryCache:{performers:{items:[{id:'old'}]}},
  entityCursors:{performers:'old-next'},entityTotals:{performers:75},
  entityPage:{performers:3},entityPageCursors:{performers:[null,'one','two']},
  entityPrefetch:new Map(),
  $:selector=>selector==='#app'?app:selector==='#entityGrid'?grid:selector==='#entityPageSize'?pageSize:null,
  $$:selector=>selector==='[data-library-filter]'?[filter]:[],pageHead:()=>'',empty:value=>value,
  paintEntityLibrary(){},loadEntityLibrary:async()=>{},
};
vm.createContext(ctx);vm.runInContext(section,ctx);
(async()=>{
  await ctx.renderEntities('performers');filter.onclick();
  assert.equal(ctx.entityLibraryFilter.performers,'female');
  assert.equal(ctx.entityLibraryCache.performers,null);
  assert.equal(ctx.entityCursors.performers,null);
  assert.equal(ctx.entityTotals.performers,null);
  assert.equal(ctx.entityPage.performers,1);
  assert.deepEqual(ctx.entityPageCursors.performers,[null]);
})().catch(error=>{console.error(error);process.exitCode=1});
""",
        APP,
    )


def test_page_size_change_resets_page_cursor_history_and_prefetches():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const section=source.slice(source.indexOf('async function renderEntities'),source.indexOf('function entityPager'));
const app={},grid={innerHTML:''},pageSize={};
const ctx={
  entityMode:{performers:'library'},entityLibraryFilter:{performers:'all'},
  entityPageSize:{performers:25},entityLibraryCache:{performers:{items:[{id:'old'}]}},
  entityCursors:{performers:'old-next'},entityTotals:{performers:75},
  entityPage:{performers:3},entityPageCursors:{performers:[null,'one','two']},
  entityPrefetch:new Map([['old-page',Promise.resolve({})]]),
  $:selector=>selector==='#app'?app:selector==='#entityGrid'?grid:selector==='#entityPageSize'?pageSize:null,
  $$:()=>[],pageHead:()=>'',empty:value=>value,
  paintEntityLibrary(){},loadEntityLibrary:async()=>{},
};
vm.createContext(ctx);vm.runInContext(section,ctx);
(async()=>{
  await ctx.renderEntities('performers');pageSize.onchange({currentTarget:{value:'50'}});
  assert.equal(ctx.entityPageSize.performers,50);
  assert.equal(ctx.entityLibraryCache.performers,null);
  assert.equal(ctx.entityCursors.performers,null);
  assert.equal(ctx.entityTotals.performers,null);
  assert.equal(ctx.entityPage.performers,1);
  assert.deepEqual(ctx.entityPageCursors.performers,[null]);
  assert.equal(ctx.entityPrefetch.size,0);
})().catch(error=>{console.error(error);process.exitCode=1});
""",
        APP,
    )


def test_rapid_next_clicks_start_only_one_visible_page_request():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const app=fs.readFileSync(process.argv[1],'utf8');
const bind=app.slice(app.indexOf('function bindEntityPager'),app.indexOf('function paintEntityLibrary'));
const grid={},next={dataset:{entityPage:'next'},disabled:false},pending=[],painted=[];
const defer=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve}};
grid.querySelectorAll=()=>[next];
const ctx={
  render(){},renderEntities(){},view:'performers',
  entityLibraryQuery:{performers:''},entityPrefetch:new Map(),
  entityPage:{performers:1},entityPageCursors:{performers:[null,'cursor-one']},
  $:selector=>selector==='#entityGrid'?grid:null,
  entityPageUrl:(type,cursor)=>cursor?`/page?cursor=${cursor}`:'/page',
  api:()=>{const request=defer();pending.push(request);return request.promise},
  paintEntityLibrary:(type,data)=>painted.push(data.items[0].id),
  prefetchEntityPage(){},notify(){},
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
vm.runInContext(bind,ctx);
(async()=>{
  ctx.bindEntityPager('performers',{has_more:true});
  const first=next.onclick();
  const second=next.onclick();
  assert.equal(pending.length,1,'the old visible page must not issue a second Next request');
  pending[0].resolve({items:[{id:'page-two'}],total:null,has_more:true,next_cursor:'cursor-two'});
  await Promise.all([first,second]);
  assert.equal(ctx.entityPage.performers,2);
  assert.deepEqual(painted,['page-two']);
})().catch(error=>{console.error(error);process.exitCode=1});
""",
        APP,
        NAVIGATION,
    )


def test_failed_next_request_restores_page_and_allows_retry():
    run_node(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const app=fs.readFileSync(process.argv[1],'utf8');
const bind=app.slice(app.indexOf('function bindEntityPager'),app.indexOf('function paintEntityLibrary'));
const grid={},next={dataset:{entityPage:'next'},disabled:false},urls=[],painted=[],notices=[];
grid.querySelectorAll=()=>[next];
let attempt=0;
const ctx={
  render(){},renderEntities(){},view:'performers',
  entityLibraryQuery:{performers:''},entityPrefetch:new Map(),
  entityPage:{performers:1},entityPageCursors:{performers:[null,'cursor-one']},
  $:selector=>selector==='#entityGrid'?grid:null,
  entityPageUrl:(type,cursor)=>cursor?`/page?cursor=${cursor}`:'/page',
  api:async url=>{urls.push(url);attempt+=1;if(attempt===1)throw new Error('network down');return {items:[{id:'page-two'}],total:null,has_more:false,next_cursor:null}},
  paintEntityLibrary:(type,data)=>painted.push(data.items[0].id),
  prefetchEntityPage(){},notify:message=>notices.push(message),
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
vm.runInContext(bind,ctx);
(async()=>{
  ctx.bindEntityPager('performers',{has_more:true});
  await next.onclick();
  assert.equal(ctx.entityPage.performers,1);
  assert.equal(next.disabled,false);
  assert.deepEqual(painted,[]);
  assert.deepEqual(notices,['network down']);
  await next.onclick();
  assert.equal(ctx.entityPage.performers,2);
  assert.deepEqual(urls,['/page?cursor=cursor-one','/page?cursor=cursor-one']);
  assert.deepEqual(painted,['page-two']);
})().catch(error=>{console.error(error);process.exitCode=1});
""",
        APP,
        NAVIGATION,
    )
