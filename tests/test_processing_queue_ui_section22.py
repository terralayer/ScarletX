import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_processing_queue_derives_attempts_elapsed_stage_and_error():
    source = (ROOT / "frontend" / "processing_queue_overrides.js").read_text(encoding="utf-8")

    assert "function attemptCount" in source
    assert "watchdog_retries" in source
    assert "function elapsedSeconds" in source
    assert "started_at" in source
    assert "completed_at" in source
    assert "function stageText" in source
    assert "native.error" in source


def test_processing_queue_renders_compact_progress_column_and_controls():
    source = (ROOT / "frontend" / "processing_queue_overrides.js").read_text(encoding="utf-8")
    base = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    activity_lists = (ROOT / "frontend" / "activity_lists.js").read_text(encoding="utf-8")
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    activity = base[base.index("async function activity()") : base.index("async function calendar")]

    for heading in ("Scene", "Stage", "Progress", "Attempts", "Elapsed", "Error"):
        assert f"<th>{heading}</th>" in source
    assert "<th>Speed</th>" not in source
    assert 'class="live-pct"' in source
    assert 'class="live-speed"' in source
    assert source.index('class="live-pct"') < source.index('class="live-speed"')
    assert 'class="live-provider"' not in source
    assert 'class="live-stage live-stage-detail"' not in source
    for action in ("pause", "resume", "cancel"):
        assert f'data-native-act="{action}"' in source
    assert "Retry" in activity_lists
    assert "Reprocess" in activity_lists
    assert "Clear Failed" in activity
    assert '<script src="/processing_queue_overrides.js"></script>' in index


def test_processing_queue_places_speed_on_its_own_line_below_percentage():
    styles = (ROOT / "frontend" / "ui_overrides.css").read_text(encoding="utf-8")

    assert ".live-speed{display:block" in styles
    assert ".live-eta{display:block" in styles


def test_processing_queue_labels_download_rate_in_megabits_per_second():
    source = (ROOT / "frontend" / "processing_queue_overrides.js").read_text(encoding="utf-8")

    assert "function speedMbps(value)" in source
    assert "return `${(bits / 1000 / 1000).toFixed(1)} Mbps`;" in source
    assert "speedMbps(x.speed_bps)" in source
    assert "speed.textContent = item.speed_bps ? speedMbps(item.speed_bps) : '—';" in source


def test_entity_libraries_use_page_navigation_instead_of_load_more():
    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'data-load-more' not in source
    assert 'data-entity-page' in source
    assert 'data-entity-page="prev"' in source
    assert 'data-entity-page="next"' in source


def test_download_toolbar_uses_persistent_bulk_pause_resume_with_retryable_errors():
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const rows=Array.from({length:11},(_,index)=>({
  external_id:`job-${index + 1}`,
  client_status:'downloading',
  scene_title:`Scene ${index + 1}`,
}));
const pauseButton={disabled:false,textContent:'Pause Downloads',dataset:{}};
const nodes=new Map([
  ['#pauseDownloader',pauseButton],
]);
const node=selector=>{
  if(!nodes.has(selector))nodes.set(selector,null);
  return nodes.get(selector);
};
const requests=[],notices=[];
let serverPaused=false,failResume=false,resyncs=0;
const api=async (url,options)=>{
  requests.push(url);
  if(url==='/api/downloads/native/control')return {paused:serverPaused};
  if(url==='/api/downloads/native/pause-all'){
    assert.equal(options.method,'POST');serverPaused=true;
    return {global_paused:true,paused:rows.length};
  }
  if(url==='/api/downloads/native/resume-all'){
    assert.equal(options.method,'POST');
    if(failResume)throw Error('resume failed');
    serverPaused=false;return {global_paused:false,resumed:rows.length};
  }
  throw Error(`Unexpected request: ${url}`);
};
const ctx={
  liveQueueSnapshot:{tracked:[]},view:'activity',
  api,$:node,post:()=>({method:'POST'}),
  resyncLiveQueue:async()=>{resyncs+=1},
  notify:(message,type)=>notices.push([message,type]),
};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
(async()=>{
  await ctx.refreshDownloadControl();
  assert.equal(pauseButton.textContent,'Pause Downloads');
  assert.equal(pauseButton.disabled,false);

  await ctx.toggleAllNativeDownloads({currentTarget:pauseButton});
  assert.equal(pauseButton.textContent,'Resume Downloads');
  assert.equal(pauseButton.disabled,false);
  assert.equal(requests.filter(url=>url==='/api/downloads/native/pause-all').length,1);
  pauseButton.textContent='stale local label';
  await ctx.refreshDownloadControl();
  assert.equal(pauseButton.textContent,'Resume Downloads','a fresh toolbar lifecycle restores persistent server pause state');

  ctx.liveQueueSnapshot={tracked:rows};
  ctx.syncDownloadPauseControl(ctx.liveQueueSnapshot);
  assert.equal(pauseButton.textContent,'Resume Downloads','persistent server pause wins over newly queued/downloading rows');

  failResume=true;
  await ctx.toggleAllNativeDownloads({currentTarget:pauseButton});
  assert.equal(pauseButton.textContent,'Resume Downloads','failed bulk resume keeps the persistent paused state retryable');
  assert.equal(pauseButton.disabled,false);
  assert(notices.some(([message,type])=>type==='error'&&message==='resume failed'));

  failResume=false;
  await ctx.toggleAllNativeDownloads({currentTarget:pauseButton});
  assert.equal(pauseButton.textContent,'Pause Downloads');
  assert.equal(pauseButton.disabled,false);
  assert.equal(requests.filter(url=>url==='/api/downloads/native/resume-all').length,2);
  assert.equal(requests.filter(url=>/^\/api\/downloads\/native\/job-/.test(url)).length,0,'bulk lifecycle must never issue per-job resume calls');
  assert.equal(resyncs,2,'only successful mutations resync the visible queue');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run(
        [
            "node",
            "-e",
            script,
            str(ROOT / "frontend" / "download_controls.js"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_clear_all_downloads_confirms_clears_and_refreshes_activity():
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const button={disabled:false,textContent:'Clear All Downloads'};
let approved=true,requests=[],refreshes=0,notices=[];
const ctx={
  api:async(url,options)=>{requests.push([url,options]);return {cleared:7,cancelled:2}},
  confirm:message=>{assert(message.includes('cancel active downloads'));return approved},
  activity:async()=>{refreshes++},
  notify:(message,type)=>notices.push([message,type]),
};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
(async()=>{
  approved=false;
  await ctx.clearAllDownloads({currentTarget:button});
  assert.equal(requests.length,0,'cancelled confirmation must not mutate downloads');
  approved=true;
  await ctx.clearAllDownloads({currentTarget:button});
  assert.equal(requests.length,1);
  assert.equal(requests[0][0],'/api/downloads');
  assert.equal(requests[0][1].method,'DELETE');
  assert.equal(refreshes,1);
  assert(notices.some(([message,type])=>type==='ok'&&message.includes('Cleared 7 downloads')));
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result = subprocess.run(
        ["node", "-e", script, str(ROOT / "frontend" / "download_controls.js")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
