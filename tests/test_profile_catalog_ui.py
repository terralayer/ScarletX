import subprocess
from pathlib import Path


def test_profile_catalog_refresh_keeps_local_scenes_and_reports_completion():
    source = Path('frontend/navigation_error_overrides.js').resolve()
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const calls=[],timers=[],button={},status={};
const list={innerHTML:'',querySelectorAll:()=>[],insertAdjacentHTML(){}};
let saved=false, phase='initial',polls=0;
const ctx={render(){},renderEntities(){},
  $:selector=>selector==='#performerSceneList'?list:selector==='#profileCatalogStatus'?status:button,
  empty:s=>s,esc:s=>s,sceneProfileList:rows=>rows.map(x=>x.title).join(','),bindProfileSceneLinks(){},
  post:body=>({method:'POST',body}),setTimeout:fn=>timers.push(fn),
  api:async(url,options)=>{
    calls.push([url,options]);
    if(url.includes('/scenes?'))return {items:[{title:saved?'Saved,New':'Saved'}],total:1,per_page:100};
    if(phase==='cached')return {status:'completed',pages_fetched:3,scenes_cached:9,last_success_at:'2026-09-18T20:15:00+00:00'};
    if(url.endsWith('/refresh')){phase='refresh';return {status:'queued',pages_fetched:0,scenes_cached:0,last_success_at:'2026-09-18T20:15:00+00:00'}}
    if(phase==='refresh')return {status:'failed',pages_fetched:2,scenes_cached:6,error:'Provider unavailable',last_success_at:'2026-09-18T20:15:00+00:00'};
    if(options)return {status:'queued',pages_fetched:0,scenes_cached:0,last_success_at:null};
    polls+=1;
    if(polls===1)return {status:'running',pages_fetched:2,scenes_cached:7,last_success_at:null};
    saved=true;return {status:'completed',pages_fetched:3,scenes_cached:9,last_success_at:'2026-09-19T17:30:00+00:00'};
  }
};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
(async()=>{
  await ctx.initProfileSceneCatalog('performers','person',7,0);
  assert.equal(list.innerHTML,'Saved');
  assert.equal(button.disabled,true);
  assert.equal(calls[0][0],'/api/library/performers/7/scenes?page=1&per_page=100');
  assert.match(status.textContent,/queued.*0 pages checked.*0 scenes saved/i);
  await timers.shift()();
  assert.match(status.textContent,/in progress.*2 pages checked.*7 scenes saved/i);
  assert.doesNotMatch(status.textContent,/complete|up to date/i);
  await timers.shift()();
  assert.equal(list.innerHTML,'Saved,New');
  assert.match(status.textContent,/complete.*3 pages checked.*9 scenes saved.*Last successful check.*2026/i);
  assert.equal(button.disabled,false);
  await button.onclick();
  assert.match(status.textContent,/queued.*0 pages checked.*0 scenes saved.*Last successful check.*2026/i);
  await timers.shift()();
  assert.match(status.textContent,/failed.*2 pages checked.*6 scenes saved.*Last successful check.*2026.*Provider unavailable/i);
  assert.doesNotMatch(status.textContent,/complete|up to date/i);
  assert.equal(list.innerHTML,'Saved,New');
  assert.equal(button.disabled,false);
  assert(calls.every(([url])=>url.startsWith('/api/library/')));
  await button.onclick();
  const beforeLeaving=calls.length;
  ctx.nextNavigationGeneration();
  await timers.shift()();
  assert.equal(calls.length,beforeLeaving,'leaving a profile must stop polling');
  phase='cached';
  const beforeReopen=calls.length;
  await ctx.initProfileSceneCatalog('performers','person',7,1);
  assert.equal(calls.slice(beforeReopen).filter(([url])=>url.includes('/scenes?')).length,1,'a complete local catalog should only load once');
  console.log('profile refresh behavior passed');
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result = subprocess.run(['node', '-e', script, str(source)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_profile_catalog_status_distinguishes_never_checked():
    source = Path('frontend/navigation_error_overrides.js').resolve()
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const button={},status={};
const list={innerHTML:'',querySelectorAll:()=>[],insertAdjacentHTML(){}};
const ctx={render(){},renderEntities(){},
  $:selector=>selector==='#performerSceneList'?list:selector==='#profileCatalogStatus'?status:button,
  empty:s=>s,esc:s=>s,sceneProfileList:()=>'',bindProfileSceneLinks(){},
  post:body=>({method:'POST',body}),setTimeout(){throw new Error('never-checked status must not poll')},
  api:async url=>url.includes('/scenes?')?{items:[],total:0,per_page:100}:{
    status:'not_started',pages_fetched:0,scenes_cached:0,
    queued_at:null,finished_at:null,last_success_at:null,error:null
  }
};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
(async()=>{
  await ctx.initProfileSceneCatalog('performers','person',7,0);
  assert.match(status.textContent,/never checked.*0 pages checked.*0 scenes saved/i);
  assert.equal(button.disabled,false);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result = subprocess.run(['node', '-e', script, str(source)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
