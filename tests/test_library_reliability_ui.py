import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_node(script, *files):
    result = subprocess.run(['node', '-e', script, *[str(ROOT / 'frontend' / f) for f in files]],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_page_transition_scrolls_only_after_success_and_restores_failed_page():
    run_node(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let page=1,scrolls=0,connected=true,finish,fail;
const button={disabled:false,isConnected:true};
const host={querySelectorAll:()=>[button],scrollIntoView:()=>scrolls++};
const ctx={notify(){}};vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
const move=target=>ctx.changeListPage({host,page:target,getPage:()=>page,setPage:value=>page=value,
 current:()=>connected,load:()=>new Promise((resolve,reject)=>{finish=resolve;fail=reject})});
(async()=>{
 let task=move(2);assert.equal(page,2);assert.equal(button.disabled,true);assert.equal(scrolls,0);
 assert.equal(await move(3),false,'ignore double clicks while a page is loading');
 finish(true);await task;assert.equal(scrolls,1);assert.equal(button.disabled,false);
 task=move(3);fail(Error('offline'));assert.equal(await task,false);assert.equal(page,2);assert.equal(scrolls,1);
 task=move(3);connected=false;finish(true);await task;assert.equal(scrolls,1,'stale navigation must not scroll');
})().catch(e=>{console.error(e);process.exitCode=1});
""", 'pagination.js')


def test_search_starts_local_and_online_pages_keep_results_during_failures():
    run_node(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let calls=[],pending=[],generation=0,view='performers',scrolls=0;
const controls={innerHTML:'',querySelectorAll:()=>[],querySelector:()=>null};
const grid={innerHTML:'',querySelectorAll:()=>[],insertAdjacentHTML(_,html){this.innerHTML+=html}};
const app={scrollIntoView:()=>scrolls++};
const ctx={view,entityMode:{performers:'search'},$:s=>s==='#entityGrid'?grid:s==='#entityNotice'?controls:s==='#app'?app:null,
 nextEntityRequest:()=>++generation,entityRequestCurrent:(_,id)=>id===generation,
 api:url=>{calls.push(url);return new Promise((resolve,reject)=>pending.push({resolve,reject}))},
 esc:String,empty:String,entityCard:(_,row)=>row.name,bindEntityActions(){},notify(){},
};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
(async()=>{
 let task=ctx.searchEntity('performers','Alexis');assert(calls[0].includes('source=local'));
 pending.shift().resolve({items:[{name:'Saved match'}],total:1,page:1,per_page:24});await task;
 assert(grid.innerHTML.includes('Saved match'));assert(controls.innerHTML.includes('Find more online'));
 task=ctx.searchEntity('performers','Alexis',{source:'online',page:1});
 assert(grid.innerHTML.includes('Saved match'),'keep local results while provider is pending');
 pending.shift().resolve({items:[{name:'Remote first'}],total:49,page:1,per_page:24});await task;
 assert(grid.innerHTML.includes('data-search-page="2"'));
 task=ctx.searchEntity('performers','Alexis',{source:'online',page:2});
 assert(calls.at(-1).includes('page=2'));pending.shift().reject(Error('provider offline'));await task;
 assert(grid.innerHTML.includes('Remote first'),'failed page leaves prior results visible');
 task=ctx.searchEntity('performers','Alexis',{source:'online',page:2});
 ctx.view='studios';pending.shift().resolve({items:[{name:'Wrong late results'}],total:49,page:2,per_page:24});await task;
 assert(!grid.innerHTML.includes('Wrong late results'));
})().catch(e=>{console.error(e);process.exitCode=1});
""", 'entity_search.js')


def test_empty_local_search_falls_back_to_online_results():
    run_node(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let calls=[],pending=[],generation=0,view='performers';
const notice={innerHTML:'',querySelector:()=>null};
const grid={innerHTML:'',querySelectorAll:()=>[],insertAdjacentHTML(_,html){this.innerHTML+=html}};
const ctx={view,$:s=>s==='#entityGrid'?grid:s==='#entityNotice'?notice:null,
 nextEntityRequest:()=>++generation,entityRequestCurrent:(_,id)=>id===generation,
 api:url=>{calls.push(url);return new Promise((resolve,reject)=>pending.push({resolve,reject}))},
 empty:String,entityCard:(_,row)=>row.name,bindEntityActions(){},notify(){},
};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
(async()=>{
 let task=ctx.searchEntity('performers','Alexis');assert(calls[0].includes('source=local'));
 pending.shift().resolve({items:[],total:0,page:1,per_page:24});await new Promise(resolve=>setTimeout(resolve,0));
 assert(calls[1].includes('source=online'),'empty local results should continue to the provider');
 pending.shift().resolve({items:[{name:'Remote match'}],total:1,page:1,per_page:24});
 await task;assert(grid.innerHTML.includes('Remote match'));
})().catch(e=>{console.error(e);process.exitCode=1});
""", 'entity_search.js')


def test_download_toolbar_uses_persistent_server_state_and_bulk_resume():
    run_node(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const button={dataset:{},disabled:false,textContent:''};let paused=true,fail=false,requests=[],finish;
const ctx={$:()=>button,post:()=>({method:'POST'}),notify(){},liveQueueSnapshot:{tracked:[]},resyncLiveQueue:async()=>{},
 api:async(url)=>{requests.push(url);if(fail)throw Error('offline');
  if(url.endsWith('/control'))return {paused};
  if(url.endsWith('/resume-all')){paused=false;return {resumed:5,global_paused:false}};
  if(url.endsWith('/pause-all'))return new Promise(resolve=>finish=()=>{paused=true;resolve({paused:2,global_paused:true})});
  throw Error(url);
 }};vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
(async()=>{
 await ctx.refreshDownloadControl();assert.equal(button.textContent,'Resume Downloads');assert.equal(button.disabled,false);
 await ctx.toggleAllNativeDownloads({currentTarget:button});assert(requests.includes('/api/downloads/native/resume-all'));
 assert.equal(button.textContent,'Pause Downloads');assert(!requests.some(url=>/\/native\/[^/]+\/resume$/.test(url)));
 let task=ctx.toggleAllNativeDownloads({currentTarget:button});assert.equal(button.disabled,true);
 finish();await task;assert.equal(button.textContent,'Resume Downloads');
 fail=true;await ctx.toggleAllNativeDownloads({currentTarget:button});assert.equal(button.textContent,'Resume Downloads');assert.equal(button.disabled,false);
})().catch(e=>{console.error(e);process.exitCode=1});
""", 'download_controls.js')


def test_failed_search_page_preserves_disabled_boundary_buttons():
    run_node(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let generation=0,fail=false,buttons=[];
const notice={innerHTML:'',querySelector:()=>null};
const grid={innerHTML:'',querySelectorAll:()=>buttons,insertAdjacentHTML(_,html){this.innerHTML+=html}};
const ctx={view:'performers',$:s=>s==='#entityGrid'?grid:s==='#entityNotice'?notice:null,
 nextEntityRequest:()=>++generation,entityRequestCurrent:(_,id)=>id===generation,
 api:async()=>{if(fail)throw Error('offline');return {items:[{name:'Last results'}],total:49,page:3,per_page:24}},
 empty:String,entityCard:(_,row)=>row.name,bindEntityActions(){},notify(){}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
(async()=>{
 await ctx.searchEntity('performers','Al',{source:'online',page:3});
 buttons=[{dataset:{searchPage:'2'},disabled:false},{dataset:{searchPage:'3'},disabled:true},{dataset:{searchPage:'4'},disabled:true}];
 fail=true;await ctx.searchEntity('performers','Al',{source:'online',page:2});
 assert.deepEqual(buttons.map(b=>b.disabled),[false,true,true]);
 assert(grid.innerHTML.includes('Last results'));
})().catch(e=>{console.error(e);process.exitCode=1});
""", 'entity_search.js')


def test_activity_shrink_failure_restores_displayed_page_and_allows_retry():
    run_node(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let calls=[],mode='initial',scrolls=0;
const host={innerHTML:'',querySelectorAll:()=>[],querySelector:()=>null,scrollIntoView:()=>scrolls++};
const ctx={view:'activity',$:()=>host,ACTIVITY_COMPLETED_PAGE_SIZE:20,ACTIVITY_FAILED_PAGE_SIZE:20,
 api:async url=>{calls.push(url);if(mode==='initial')return {scarletx:[{title:'Page three'}],total:100};
   if(url.includes('offset=60'))return {scarletx:[],total:40};
   if(mode==='fail')throw Error('replacement offline');
   return {scarletx:[{title:'Page two'}],total:40};},
 esc:String,bytes:String,fmtDate:String,empty:String,activityPager:(kind,page)=>`pager ${page}`,notify(){}};
vm.createContext(ctx);for(const path of process.argv.slice(1))vm.runInContext(fs.readFileSync(path,'utf8'),ctx);
(async()=>{
 await ctx.changeActivitySectionPage('completed',3);const old=host.innerHTML;
 mode='fail';assert.equal(await ctx.changeActivitySectionPage('completed',4),false);
 assert.equal(host.innerHTML,old);assert.equal(vm.runInContext('activitySections.completed.page',ctx),3);
 assert.equal(scrolls,1);mode='success';
 assert.equal(await ctx.changeActivitySectionPage('completed',2),true);assert(host.innerHTML.includes('Page two'));
 assert.equal(scrolls,2);
})().catch(e=>{console.error(e);process.exitCode=1});
""", 'pagination.js', 'activity_lists.js')


def test_activity_sections_page_independently_and_keep_current_rows_on_failure():
    run_node(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let calls=[],pending=[],scrolls=0;
const hosts=Object.fromEntries(['Completed','Failed','History'].map(name=>['#activity'+name,
 {innerHTML:'old '+name,querySelectorAll:()=>[],querySelector:()=>null,scrollIntoView:()=>scrolls++}]));
const ctx={view:'activity',$:s=>hosts[s],api:url=>{calls.push(url);return new Promise((resolve,reject)=>pending.push({resolve,reject}))},
 ACTIVITY_COMPLETED_PAGE_SIZE:20,ACTIVITY_FAILED_PAGE_SIZE:20,activityCompletedPage:1,activityFailedPage:1,
 esc:String,bytes:String,fmtDate:String,empty:String,activityPager:(kind,page)=>`pager ${kind} ${page}`,notify(){},post(){}};
vm.createContext(ctx);for(const path of process.argv.slice(1))vm.runInContext(fs.readFileSync(path,'utf8'),ctx);
(async()=>{
 for(const [kind,data,expected] of [['completed',{scarletx:[{title:'Finished'}],total:45},'Finished'],
 ['failed',{scarletx:[{title:'Failed job'}],total:45},'Failed job'],
 ['history',{items:[{message:'History entry'}],total:45,event_counts:{}},'History entry']]){
   let task=ctx.changeActivitySectionPage(kind,2);
   assert.equal(calls.length,1,'only requested section should fetch');
   assert(!calls[0].includes('/api/activity/queue'));pending.shift().resolve(data);await task;
   const host=hosts['#activity'+kind[0].toUpperCase()+kind.slice(1)];assert(host.innerHTML.includes(expected));
   const previous=host.innerHTML,oldScrolls=scrolls;
   task=ctx.changeActivitySectionPage(kind,3);pending.shift().reject(Error('offline'));await task;
   assert.equal(host.innerHTML,previous);assert.equal(scrolls,oldScrolls);
   task=ctx.changeActivitySectionPage(kind,3);ctx.view='scenes';pending.shift().resolve(data);await task;
   assert.equal(host.innerHTML,previous);assert.equal(scrolls,oldScrolls);ctx.view='activity';calls=[];
 }
})().catch(e=>{console.error(e);process.exitCode=1});
""", 'pagination.js', 'activity_lists.js')
