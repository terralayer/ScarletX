const MEDIA_LIBRARY_PAGE_SIZE=50;
let activityQueueTotal=0;
let activityQueuePageRows=[];
let activityQueueCountBusy=false;
let activityQueuePageRequest=0;
let activityQueueTransition=null;
let activityQueueRefreshPending=false;
let activityQueuePendingSnapshot=null;
let mediaLibraryPage=1;
let mediaLibraryCursors=[null];
let mediaLibraryRequest=0;
let mediaLibraryPageRequest=0;

function liveConnectionCapacity(x){
  let providerTotal=(x.provider_stats||[]).reduce((sum,p)=>sum+Math.max(0,Number(p.connections||0)),0);
  let reported=Math.max(0,Number(x.connection_capacity||x.connection_cap||0));
  if(providerTotal&&reported)return Math.min(providerTotal,reported);
  return providerTotal||reported||Math.max(0,Number(x.active_connections||0));
}

async function updateChrome(){
  try{
    let [count,d]=await Promise.all([api('/api/activity/count').catch(()=>({active:0})),api('/api/system/diskspace').catch(()=>[])]);
    activityQueueTotal=Math.max(0,Number(count.active||0));
    $('#queueBadge').textContent=activityQueueTotal;
    let x=d.find(i=>i.exists&&i.total_bytes)||d.find(i=>i.exists);
    if(x&&x.total_bytes){let pct=Math.round((x.used_bytes/x.total_bytes)*100);$('#storageBar').style.width=`${pct}%`;$('#storageUsed').textContent=`${bytes(x.used_bytes)} / ${bytes(x.total_bytes)}`;$('#storagePct').textContent=`${pct}%`}
  }catch{}
}

async function refreshActivityQueueTotal(){
  if(activityQueueTransition){activityQueueRefreshPending=true;return activityQueueTotal}
  if(activityQueueCountBusy)return activityQueueCountBusy;
  activityQueueCountBusy=(async()=>{try{
    let result=await api('/api/activity/count');
    if(activityQueueTransition){activityQueueRefreshPending=true;return activityQueueTotal}
    const nextTotal=Math.max(0,Number(result.active||0)),pages=Math.max(1,Math.ceil(nextTotal/ACTIVITY_QUEUE_PAGE_SIZE));
    $('#queueBadge').textContent=nextTotal;
    if(activityQueuePage>pages)return nextTotal;
    activityQueueTotal=nextTotal;
    let el=$('#activityQueue');
    if(el&&activityQueuePage===1){
      let oldPager=el.querySelector('.queue-pagination'),pager=activityQueuePagerHtml(activityQueueTotal);
      if(oldPager)oldPager.outerHTML=pager;
      else if(pager)el.insertAdjacentHTML('beforeend',pager);
      bindActivityQueuePager(el,activityQueueTotal);
    }
  }catch(_){}
  return activityQueueTotal})();
  try{return await activityQueueCountBusy}finally{activityQueueCountBusy=false}
}

function activityQueuePagerHtml(total){
  if(total<=ACTIVITY_QUEUE_PAGE_SIZE)return '';
  let pages=Math.max(1,Math.ceil(total/ACTIVITY_QUEUE_PAGE_SIZE));
  activityQueuePage=Math.min(Math.max(1,activityQueuePage),pages);
  let numbers=Array.from({length:pages},(_,i)=>i+1).filter(n=>pages<=7||n===1||n===pages||Math.abs(n-activityQueuePage)<=1).map(n=>`<button class="btn small" data-queue-page="${n}" ${n===activityQueuePage?'disabled':''}>${n}</button>`).join('');
  return `<div class="pagination-bar queue-pagination"><button class="btn small" data-queue-page="prev" ${activityQueuePage===1?'disabled':''}>Previous</button>${numbers}<button class="btn small" data-queue-page="next" ${activityQueuePage===pages?'disabled':''}>Next</button></div>`;
}

function activityQueueHtml(rows){
  return rows.length?`<div class="tablewrap" style="border:0;border-radius:0"><table class="table"><thead><tr><th>Scene</th><th>Status</th><th>Progress</th><th>Speed</th><th></th></tr></thead><tbody>${rows.map(x=>{let pct=x.progress==null?'—':`${Number(x.progress).toFixed(1)}%`,speed=x.speed_bps?`${bytes(x.speed_bps)}/s`:'—',eta=x.eta_seconds!=null?`${Math.floor(x.eta_seconds/60)}m ${x.eta_seconds%60}s`:'—',state=x.client_status||x.status,done=x.downloaded_bytes!=null?bytes(x.downloaded_bytes):'—',total=x.total_bytes?bytes(x.total_bytes):'—',capacity=liveConnectionCapacity(x),buttons=['queued','downloading'].includes(state)?`<button class="btn small" data-native-act="pause" data-job="${esc(x.external_id)}">Pause</button><button class="btn small danger" data-native-act="cancel" data-job="${esc(x.external_id)}">Cancel</button>`:state==='postprocessing'?`<button class="btn small danger" data-native-act="cancel" data-job="${esc(x.external_id)}">Cancel</button>`:state==='paused'?`<button class="btn small primary" data-native-act="resume" data-job="${esc(x.external_id)}">Resume</button>`:'';return `<tr data-live-job="${esc(x.external_id)}"><td><b class="live-title">${esc(x.scene_title||x.release_title||'Download')}</b></td><td><span class="state warn live-status">${esc(state)}</span><small class="live-stage">${state==='postprocessing'?esc(x.postprocess_note||'Preparing media…'):''}</small></td><td><b class="live-pct">${pct}</b><small class="live-bytes">${done} / ${total}</small><div class="mini-progress" ${x.progress==null?'style="display:none"':''}><i class="live-bar" style="width:${Math.min(100,Number(x.progress||0))}%"></i></div></td><td><b class="live-speed">${speed}</b><span class="live-eta-row"><small class="live-eta">${eta!=='—'?`ETA ${eta}`:''}</small></span><small class="live-provider">${x.provider?`Best: ${esc(x.provider)}${x.active_connections?` • ${x.active_connections}/${capacity||x.active_connections} conns`:''}`:(x.active_connections?`${x.active_connections}/${capacity||x.active_connections} conns`:'')}</small></td><td><div class="actions live-actions">${buttons}</div></td></tr>`}).join('')}</tbody></table></div>`:empty('No active downloads.');
}

async function loadActivityQueuePage(el=$('#activityQueue')){
  const requestId=++activityQueuePageRequest,requestedPage=activityQueuePage;
  let displayPage=requestedPage;
  let data=await api(`/api/activity/page?page=${activityQueuePage}&limit=${ACTIVITY_QUEUE_PAGE_SIZE}`);
  while(true){
    if(view!=='activity'||requestId!==activityQueuePageRequest||$('#activityQueue')!==el||activityQueuePage!==requestedPage)return false;
    const responsePage=Math.max(1,Number(data.page||displayPage));
    const total=Math.max(0,Number(data.total||0)),pages=Math.max(1,Math.ceil(total/ACTIVITY_QUEUE_PAGE_SIZE));
    if(displayPage>pages){displayPage=pages;data=await api(`/api/activity/page?page=${displayPage}&limit=${ACTIVITY_QUEUE_PAGE_SIZE}`);continue}
    if(responsePage!==displayPage)return false;
    const rows=data.items||[];
    activityQueuePage=displayPage;
    activityQueueTotal=total;
    activityQueuePageRows=rows;
    el.innerHTML=activityQueueHtml(rows)+activityQueuePagerHtml(total);
    bindActivityQueuePager(el,total);
    $('#queueBadge').textContent=total;
    return true;
  }
}

function bindActivityQueuePager(el,total){
  let pages=Math.max(1,Math.ceil(total/ACTIVITY_QUEUE_PAGE_SIZE));
  el.querySelectorAll('[data-queue-page]').forEach(button=>button.onclick=async()=>{
    if(activityQueueTransition)return false;
    let action=button.dataset.queuePage;
    let target=action==='prev'?Math.max(1,activityQueuePage-1):action==='next'?Math.min(pages,activityQueuePage+1):Math.min(pages,Math.max(1,Number(action)||1));
    const transition={host:el};
    activityQueueTransition=transition;
    let changed=false;
    try{
      changed=await changeListPage({host:el,page:target,getPage:()=>activityQueuePage,setPage:page=>activityQueuePage=page,
        load:()=>loadActivityQueuePage(el),current:()=>view==='activity'&&$('#activityQueue')===el});
    }finally{
      if(activityQueueTransition===transition){
        const snapshot=activityQueuePendingSnapshot,refresh=activityQueueRefreshPending;
        activityQueueTransition=null;activityQueuePendingSnapshot=null;activityQueueRefreshPending=false;
        if(view==='activity'&&$('#activityQueue')===el&&snapshot)applyLiveQueue(snapshot);
        if(view==='activity'&&$('#activityQueue')===el&&refresh)refreshActivityQueueAfterEvent().catch(()=>{});
      }
    }
    return changed;
  });
}

function applyLiveQueue(q){
  if(activityQueueTransition){activityQueuePendingSnapshot=q;activityQueueRefreshPending=true;return false}
  let snapshotRows=q.tracked||[],el=$('#activityQueue'),total=activityQueueTotal||snapshotRows.length;
  let visibleRows=activityQueuePage===1?snapshotRows.slice(0,ACTIVITY_QUEUE_PAGE_SIZE):activityQueuePageRows;
  if(activityQueuePage===1)activityQueuePageRows=visibleRows;
  if(el){
    let current=[...el.querySelectorAll('[data-live-job]')],currentIds=current.map(r=>r.dataset.liveJob),nextIds=visibleRows.map(x=>String(x.external_id||''));
    if(!current.length||currentIds.join('|')!==nextIds.join('|')){
      el.innerHTML=activityQueueHtml(visibleRows)+activityQueuePagerHtml(total);
    }else{
      visibleRows.forEach((x,i)=>{let r=current[i],pct=x.progress==null?null:Number(x.progress),state=x.client_status||x.status,speed=x.speed_bps?`${bytes(x.speed_bps)}/s`:'—',eta=x.eta_seconds!=null?`${Math.floor(x.eta_seconds/60)}m ${x.eta_seconds%60}s`:'',capacity=liveConnectionCapacity(x),buttons=['queued','downloading'].includes(state)?`<button class="btn small" data-native-act="pause" data-job="${esc(x.external_id)}">Pause</button><button class="btn small danger" data-native-act="cancel" data-job="${esc(x.external_id)}">Cancel</button>`:state==='postprocessing'?`<button class="btn small danger" data-native-act="cancel" data-job="${esc(x.external_id)}">Cancel</button>`:state==='paused'?`<button class="btn small primary" data-native-act="resume" data-job="${esc(x.external_id)}">Resume</button>`:'';r.querySelector('.live-title').textContent=x.scene_title||x.release_title||'Download';r.querySelector('.live-status').textContent=state;let ls=r.querySelector('.live-stage');if(ls)ls.textContent=state==='postprocessing'?(x.postprocess_note||'Preparing media…'):'';r.querySelector('.live-pct').textContent=pct==null?'—':`${pct.toFixed(1)}%`;r.querySelector('.live-bytes').textContent=`${x.downloaded_bytes!=null?bytes(x.downloaded_bytes):'—'} / ${x.total_bytes?bytes(x.total_bytes):'—'}`;let pb=r.querySelector('.mini-progress');pb.style.display=pct==null?'none':'';r.querySelector('.live-bar').style.width=`${Math.min(100,pct||0)}%`;r.querySelector('.live-speed').textContent=speed;r.querySelector('.live-eta').textContent=eta?`ETA ${eta}`:'';let lp=r.querySelector('.live-provider');if(lp)lp.textContent=x.provider?`Best: ${x.provider}${x.active_connections?` • ${x.active_connections}/${capacity||x.active_connections} conns`:''}`:(x.active_connections?`${x.active_connections}/${capacity||x.active_connections} conns`:'');r.querySelector('.live-actions').innerHTML=buttons});
      let oldPager=el.querySelector('.queue-pagination');
      let pager=activityQueuePagerHtml(total);
      if(oldPager)oldPager.outerHTML=pager;
      else if(pager)el.insertAdjacentHTML('beforeend',pager);
    }
    bindActivityQueuePager(el,total);
  }
  $('#queueBadge').textContent=activityQueueTotal||snapshotRows.length;
  return true;
}

async function refreshActivityQueueAfterEvent(){
  if(activityQueueTransition){activityQueueRefreshPending=true;return false}
  await refreshActivityQueueTotal();
  if(activityQueueTransition){activityQueueRefreshPending=true;return false}
  let el=$('#activityQueue');
  if(view==='activity'&&activityQueuePage>1&&el)return loadActivityQueuePage(el);
  return view==='activity';
}

window.addEventListener('scarletx:queue-event',e=>{
  let kind=e.detail?.kind;
  if(!['snapshot','transition','resync'].includes(kind))return;
  refreshActivityQueueAfterEvent().catch(()=>{});
});
window.addEventListener('scarletx:app-open', refreshActivityQueueTotal);

function mediaFileRowsHtml(files){
  return files.map(x=>`<tr data-media-row="${x.id}"><td><div class="library-scene-cell"><div class="library-scene-copy"><button class="scene-title" data-library-scene="${x.scene_id}">${esc(x.scene_title)}</button><div class="library-studio-meta"><small class="library-studio">${x.studio?`Studio: ${esc(x.studio)}`:'Studio: —'}</small><small class="library-release">Release: ${fmtDate(x.release_date)}</small></div>${x.missing?'<small><span class="state bad">Missing</span></small>':''}</div></div></td><td>${bytes(x.size_bytes)}</td><td>${x.position_seconds?`${durationText(x.position_seconds)} / ${durationText(x.duration_seconds)}`:x.play_count?'Played':'Unwatched'}${x.favorite?'<small>★ Favorite</small>':''}</td><td><div class="actions"><button class="btn small primary" data-play-media="${x.id}" ${x.missing?'disabled':''}>Play</button><button class="btn small" data-probe-media="${x.id}">Refresh</button><button class="btn small" data-favorite-media="${x.id}" data-fav="${x.favorite?'1':'0'}">${x.favorite?'★':'☆'}</button></div></td></tr>`).join('');
}

function mediaFilesHtml(files,total,hasMore=false){
  if(!files.length)return empty('No indexed media files yet. Configure a scene root folder, then scan the library.');
  return `<div class="tablewrap" style="border:0;border-radius:0"><table class="table"><thead><tr><th>Scene</th><th>Size</th><th>Watch</th><th></th></tr></thead><tbody>${mediaFileRowsHtml(files)}</tbody></table></div>`;
}

function mediaLibraryPagerHtml(total,hasMore){
  let totalPages=Math.max(1,Math.ceil(total/MEDIA_LIBRARY_PAGE_SIZE));
  let numbers=Array.from({length:mediaLibraryPage},(_,i)=>i+1).filter(n=>mediaLibraryPage<=7||n===1||Math.abs(n-mediaLibraryPage)<=1).map(n=>`<button class="btn small" data-library-page="${n}" ${n===mediaLibraryPage?'disabled':''}>${n}</button>`).join('');
  return `<div class="pagination-bar library-pagination"><button class="btn small" data-library-page="prev" ${mediaLibraryPage===1?'disabled':''}>Previous</button>${numbers}<button class="btn small" data-library-page="next" ${!hasMore?'disabled':''}>Next</button></div>`;
}

async function loadMediaLibraryPage(total,filesHost=$('#libraryFiles')){
  const requestId=++mediaLibraryPageRequest,requestedPage=mediaLibraryPage;
  let cursor=mediaLibraryCursors[requestedPage-1]||null;
  let url=`/api/media-library/files/page?limit=${MEDIA_LIBRARY_PAGE_SIZE}`;
  if(cursor)url+=`&cursor=${encodeURIComponent(cursor)}`;
  let files=await api(url);
  if(view!=='library'||requestId!==mediaLibraryPageRequest||$('#libraryFiles')!==filesHost||mediaLibraryPage!==requestedPage)return false;
  const rows=files.items||[],nextCursor=files.next_cursor||null,hasMore=!!files.has_more;
  mediaLibraryRows=rows;
  mediaLibraryCursor=nextCursor;
  mediaLibraryHasMore=hasMore;
  if(hasMore&&nextCursor)mediaLibraryCursors[requestedPage]=nextCursor;
  filesHost.innerHTML=mediaFilesHtml(rows,total,hasMore)+mediaLibraryPagerHtml(total,hasMore);
  return true;
}

function bindMediaLibraryActions(filesHost,total){
  filesHost.onclick=async e=>{
    let page=e.target.closest('[data-library-page]');
    if(page){
      let action=page.dataset.libraryPage,target=action==='prev'?Math.max(1,mediaLibraryPage-1):action==='next'&&mediaLibraryHasMore?mediaLibraryPage+1:Number(action);
      if(!Number.isInteger(target)||target<1)return false;
      return changeListPage({host:filesHost,page:target,getPage:()=>mediaLibraryPage,setPage:value=>mediaLibraryPage=value,
        load:()=>loadMediaLibraryPage(total,filesHost),current:()=>view==='library'&&$('#libraryFiles')===filesHost});
    }
    let play=e.target.closest('[data-play-media]');
    if(play)return playMedia(Number(play.dataset.playMedia));
    let scene=e.target.closest('[data-library-scene]');
    if(scene)return openLocalScene(Number(scene.dataset.libraryScene));
    let probe=e.target.closest('[data-probe-media]');
    if(probe){probe.disabled=true;try{await api(`/api/media-files/${probe.dataset.probeMedia}/probe`,post());notify('Media information refreshed.','ok');mediaLibrary()}catch(err){notify(err.message,'error');probe.disabled=false}return}
    let fav=e.target.closest('[data-favorite-media]');
    if(fav){await api(`/api/media-files/${fav.dataset.favoriteMedia}/playback`,patch({favorite:fav.dataset.fav!=='1'}));return mediaLibrary()}
  };
}

async function mediaLibrary(){
  const requestId=++mediaLibraryRequest;
  $('#app').innerHTML=pageHead('Library','',`<button class="btn" id="scanLibrary">Scan Library</button><button class="btn danger" id="clearMissing">Clear Missing</button>`)+`<div class="stats" id="libraryStats"></div><div class="panel"><div class="panel-head"><h2>Media Files</h2></div><div id="libraryFiles"></div></div><div style="height:14px"></div><div class="dashgrid"><div class="panel"><div class="panel-head"><h2>Duplicates</h2></div><div id="libraryDuplicates"></div></div><div class="panel"><div class="panel-head"><h2>Unmatched Files</h2></div><div id="libraryUnmatched"></div></div><div class="panel"><div class="panel-head"><h2>Media Tools</h2></div><div id="libraryTools" class="rows"></div></div></div>`;
  const filesHost=$('#libraryFiles'),statsHost=$('#libraryStats'),duplicatesHost=$('#libraryDuplicates'),unmatchedHost=$('#libraryUnmatched'),toolsHost=$('#libraryTools');
  $('#scanLibrary').onclick=async e=>{e.currentTarget.disabled=true;e.currentTarget.textContent='Scanning…';try{let r=await api('/api/media-library/scan',post());notify(r.already_running?'Library scan is already running.':'Library scan started in the background.','ok');mediaLibraryPage=1;mediaLibraryCursors=[null];setTimeout(mediaLibrary,1200)}catch(err){notify(err.message,'error');e.currentTarget.disabled=false}};
  $('#clearMissing').onclick=async()=>{if(!confirm('Remove database entries for media files that no longer exist?'))return;try{await api('/api/media-library/missing',{method:'DELETE'});notify('Missing-file entries cleared.','ok');mediaLibraryPage=1;mediaLibraryCursors=[null];mediaLibrary()}catch(err){notify(err.message,'error')}};
  try{
    let [status,dupes,unmatched]=await Promise.all([api('/api/media-library/status'),api('/api/media-library/duplicates'),api('/api/media-library/unmatched?limit=200&offset=0')]);
    if(view!=='library'||requestId!==mediaLibraryRequest||$('#libraryFiles')!==filesHost||$('#libraryStats')!==statsHost)return false;
    let totalPages=Math.max(1,Math.ceil(status.files/MEDIA_LIBRARY_PAGE_SIZE));
    if(mediaLibraryPage>totalPages){mediaLibraryPage=1;mediaLibraryCursors=[null]}
    statsHost.innerHTML=[['▶','Files',status.files,'Indexed'],['▱','Storage',bytes(status.total_bytes),'Local media'],['!','Missing',status.missing,'Needs attention'],['≡','Duplicates',status.duplicate_groups,'Fingerprint groups'],['?','Unmatched',status.unmatched,'Needs scene match']].map(x=>`<div class="stat"><div class="stat-icon">${x[0]}</div><div><small>${x[1]}</small><strong>${x[2]}</strong><em>${x[3]}</em></div></div>`).join('');
    if(!await loadMediaLibraryPage(status.files,filesHost))return false;
    bindMediaLibraryActions(filesHost,status.files);
    if(view!=='library'||requestId!==mediaLibraryRequest||$('#libraryFiles')!==filesHost)return false;
    duplicatesHost.innerHTML=dupes.length?dupes.map(g=>`<div class="row"><div class="rowicon">≡</div><div><b>${g.files.length} matching files</b><small>${g.files.map(f=>esc(f.filename)).join('<br>')}</small></div></div>`).join(''):empty('No duplicate fingerprints found.');
    unmatchedHost.innerHTML=unmatched.filter(x=>!x.missing).length?unmatched.filter(x=>!x.missing).slice(0,30).map(x=>`<div class="row"><div class="rowicon">?</div><div><b>${esc(x.display_name)}</b><small>${esc(x.path)}</small></div><span>${bytes(x.size_bytes)}</span></div>`).join(''):empty('No unmatched files.');
    let tools=status.tools||{};toolsHost.innerHTML=`<div class="row"><div class="rowicon">▶</div><div><b>FFmpeg</b><small>Playback assets and previews</small></div><span class="state ${tools.ffmpeg?'good':'bad'}">${tools.ffmpeg?'Ready':'Missing'}</span></div><div class="row"><div class="rowicon">i</div><div><b>FFprobe</b><small>Media analysis</small></div><span class="state ${tools.ffprobe?'good':'bad'}">${tools.ffprobe?'Ready':'Missing'}</span></div>${status.latest_scan?`<div class="row"><div class="rowicon">↻</div><div><b>Last Scan</b><small>${fmtDate(status.latest_scan.finished_at||status.latest_scan.created_at)}</small></div><span class="state ${status.latest_scan.status==='completed'?'good':status.latest_scan.status==='failed'?'bad':'warn'}">${esc(status.latest_scan.status)}</span></div>`:''}`;
    return true;
  }catch(e){if(view==='library'&&requestId===mediaLibraryRequest&&$('#libraryFiles')===filesHost)notify(e.message,'error');return false}
}
