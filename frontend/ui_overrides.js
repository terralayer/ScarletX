const MEDIA_LIBRARY_PAGE_SIZE=50;
let activityQueueTotal=0;
let activityQueuePageRows=[];
let activityQueueCountBusy=false;
let mediaLibraryPage=1;
let mediaLibraryCursors=[null];

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
  if(activityQueueCountBusy)return activityQueueTotal;
  activityQueueCountBusy=true;
  try{
    let result=await api('/api/activity/count');
    activityQueueTotal=Math.max(0,Number(result.active||0));
    $('#queueBadge').textContent=activityQueueTotal;
    let el=$('#activityQueue');
    if(el){
      let pages=Math.max(1,Math.ceil(activityQueueTotal/ACTIVITY_QUEUE_PAGE_SIZE));
      if(activityQueuePage>pages)activityQueuePage=pages;
      let oldPager=el.querySelector('.queue-pagination'),pager=activityQueuePagerHtml(activityQueueTotal);
      if(oldPager)oldPager.outerHTML=pager;
      else if(pager)el.insertAdjacentHTML('beforeend',pager);
      bindActivityQueuePager(el,activityQueueTotal);
    }
  }catch(_){}
  finally{activityQueueCountBusy=false}
  return activityQueueTotal;
}

function activityQueuePagerHtml(total){
  if(total<=ACTIVITY_QUEUE_PAGE_SIZE)return '';
  let pages=Math.max(1,Math.ceil(total/ACTIVITY_QUEUE_PAGE_SIZE));
  activityQueuePage=Math.min(Math.max(1,activityQueuePage),pages);
  return `<div class="pagination-bar queue-pagination"><button class="btn small" data-queue-page="first" ${activityQueuePage===1?'disabled':''}>First</button><button class="btn small" data-queue-page="prev" ${activityQueuePage===1?'disabled':''}>Previous</button><span class="page-status">Page ${activityQueuePage} of ${pages} · ${total} jobs</span><button class="btn small" data-queue-page="next" ${activityQueuePage===pages?'disabled':''}>Next</button><button class="btn small" data-queue-page="last" ${activityQueuePage===pages?'disabled':''}>Last</button></div>`;
}

function activityQueueHtml(rows){
  return rows.length?`<div class="tablewrap" style="border:0;border-radius:0"><table class="table"><thead><tr><th>Scene</th><th>Status</th><th>Progress</th><th>Speed</th><th></th></tr></thead><tbody>${rows.map(x=>{let pct=x.progress==null?'—':`${Number(x.progress).toFixed(1)}%`,speed=x.speed_bps?`${bytes(x.speed_bps)}/s`:'—',eta=x.eta_seconds!=null?`${Math.floor(x.eta_seconds/60)}m ${x.eta_seconds%60}s`:'—',state=x.client_status||x.status,done=x.downloaded_bytes!=null?bytes(x.downloaded_bytes):'—',total=x.total_bytes?bytes(x.total_bytes):'—',capacity=liveConnectionCapacity(x),buttons=['queued','downloading'].includes(state)?`<button class="btn small" data-native-act="pause" data-job="${esc(x.external_id)}">Pause</button><button class="btn small danger" data-native-act="cancel" data-job="${esc(x.external_id)}">Cancel</button>`:state==='postprocessing'?`<button class="btn small danger" data-native-act="cancel" data-job="${esc(x.external_id)}">Cancel</button>`:state==='paused'?`<button class="btn small primary" data-native-act="resume" data-job="${esc(x.external_id)}">Resume</button>`:'';return `<tr data-live-job="${esc(x.external_id)}"><td><b class="live-title">${esc(x.scene_title||x.release_title||'Download')}</b></td><td><span class="state warn live-status">${esc(state)}</span><small class="live-stage">${state==='postprocessing'?esc(x.postprocess_note||'Preparing media…'):''}</small></td><td><b class="live-pct">${pct}</b><small class="live-bytes">${done} / ${total}</small><div class="mini-progress" ${x.progress==null?'style="display:none"':''}><i class="live-bar" style="width:${Math.min(100,Number(x.progress||0))}%"></i></div></td><td><b class="live-speed">${speed}</b><span class="live-eta-row"><small class="live-eta">${eta!=='—'?`ETA ${eta}`:''}</small></span><small class="live-provider">${x.provider?`Best: ${esc(x.provider)}${x.active_connections?` • ${x.active_connections}/${capacity||x.active_connections} conns`:''}`:(x.active_connections?`${x.active_connections}/${capacity||x.active_connections} conns`:'')}</small></td><td><div class="actions live-actions">${buttons}</div></td></tr>`}).join('')}</tbody></table></div>`:empty('No active downloads.');
}

async function loadActivityQueuePage(){
  let data=await api(`/api/activity/page?page=${activityQueuePage}&limit=${ACTIVITY_QUEUE_PAGE_SIZE}`);
  activityQueueTotal=Math.max(0,Number(data.total||0));
  activityQueuePage=Math.max(1,Number(data.page||activityQueuePage));
  activityQueuePageRows=data.items||[];
  let el=$('#activityQueue');
  if(el){
    el.innerHTML=activityQueueHtml(activityQueuePageRows)+activityQueuePagerHtml(activityQueueTotal);
    bindActivityQueuePager(el,activityQueueTotal);
  }
  $('#queueBadge').textContent=activityQueueTotal;
}

function bindActivityQueuePager(el,total){
  let pages=Math.max(1,Math.ceil(total/ACTIVITY_QUEUE_PAGE_SIZE));
  el.querySelectorAll('[data-queue-page]').forEach(button=>button.onclick=async()=>{
    let action=button.dataset.queuePage;
    if(action==='first')activityQueuePage=1;
    if(action==='prev')activityQueuePage=Math.max(1,activityQueuePage-1);
    if(action==='next')activityQueuePage=Math.min(pages,activityQueuePage+1);
    if(action==='last')activityQueuePage=pages;
    try{await loadActivityQueuePage()}catch(err){notify(err.message,'error')}
  });
}

function applyLiveQueue(q){
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
}

window.addEventListener('scarletx:queue-event',e=>{
  let kind=e.detail?.kind;
  if(!['snapshot','transition','resync'].includes(kind))return;
  refreshActivityQueueTotal().then(()=>{
    if(view==='activity'&&activityQueuePage>1)loadActivityQueuePage().catch(()=>{});
  });
});
refreshActivityQueueTotal();

function mediaFileRowsHtml(files){
  return files.map(x=>{let art=x.scene_id?`/api/artwork/scenes/${encodeURIComponent(x.scene_id)}?size=card`:'';return `<tr data-media-row="${x.id}"><td><div class="library-scene-cell">${art?`<span class="library-scene-thumb"><img src="${esc(art)}" alt="" loading="lazy" onerror="this.closest('.library-scene-thumb').classList.add('missing-art');this.remove()"></span>`:''}<div class="library-scene-copy"><button class="scene-title" data-library-scene="${x.scene_id}">${esc(x.scene_title)}</button><small class="library-studio">${x.studio?`Studio: ${esc(x.studio)}`:'Studio: —'}</small><small class="studio-release">${fmtDate(x.release_date)}</small>${x.missing?'<small><span class="state bad">Missing</span></small>':''}</div></div></td><td>${bytes(x.size_bytes)}</td><td>${x.position_seconds?`${durationText(x.position_seconds)} / ${durationText(x.duration_seconds)}`:x.play_count?'Played':'Unwatched'}${x.favorite?'<small>★ Favorite</small>':''}</td><td><div class="actions"><button class="btn small primary" data-play-media="${x.id}" ${x.missing?'disabled':''}>Play</button><button class="btn small" data-probe-media="${x.id}">Refresh</button><button class="btn small" data-favorite-media="${x.id}" data-fav="${x.favorite?'1':'0'}">${x.favorite?'★':'☆'}</button></div></td></tr>`}).join('');
}

function mediaFilesHtml(files,total,hasMore=false){
  if(!files.length)return empty('No indexed media files yet. Configure a scene root folder, then scan the library.');
  return `<div class="tablewrap" style="border:0;border-radius:0"><table class="table"><thead><tr><th>Scene</th><th>Size</th><th>Watch</th><th></th></tr></thead><tbody>${mediaFileRowsHtml(files)}</tbody></table></div>`;
}

function mediaLibraryPagerHtml(total,hasMore){
  let totalPages=Math.max(1,Math.ceil(total/MEDIA_LIBRARY_PAGE_SIZE));
  return `<div class="pagination-bar library-pagination"><button class="btn small" data-library-page="first" ${mediaLibraryPage===1?'disabled':''}>First</button><button class="btn small" data-library-page="prev" ${mediaLibraryPage===1?'disabled':''}>Previous</button><span class="page-status">Page ${mediaLibraryPage} of ${totalPages} · ${total} files</span><button class="btn small" data-library-page="next" ${!hasMore?'disabled':''}>Next</button></div>`;
}

async function loadMediaLibraryPage(total){
  let cursor=mediaLibraryCursors[mediaLibraryPage-1]||null;
  let url=`/api/media-library/files/page?limit=${MEDIA_LIBRARY_PAGE_SIZE}`;
  if(cursor)url+=`&cursor=${encodeURIComponent(cursor)}`;
  let files=await api(url);
  mediaLibraryRows=files.items||[];
  mediaLibraryCursor=files.next_cursor||null;
  mediaLibraryHasMore=!!files.has_more;
  if(mediaLibraryHasMore&&files.next_cursor)mediaLibraryCursors[mediaLibraryPage]=files.next_cursor;
  $('#libraryFiles').innerHTML=mediaFilesHtml(mediaLibraryRows,total,mediaLibraryHasMore)+mediaLibraryPagerHtml(total,mediaLibraryHasMore);
}

async function mediaLibrary(){
  $('#app').innerHTML=pageHead('Library','',`<button class="btn" id="scanLibrary">Scan Library</button><button class="btn danger" id="clearMissing">Clear Missing</button>`)+`<div class="stats" id="libraryStats"></div><div class="panel"><div class="panel-head"><h2>Media Files</h2></div><div id="libraryFiles"></div></div><div style="height:14px"></div><div class="dashgrid"><div class="panel"><div class="panel-head"><h2>Duplicates</h2></div><div id="libraryDuplicates"></div></div><div class="panel"><div class="panel-head"><h2>Unmatched Files</h2></div><div id="libraryUnmatched"></div></div><div class="panel"><div class="panel-head"><h2>Media Tools</h2></div><div id="libraryTools" class="rows"></div></div></div>`;
  $('#scanLibrary').onclick=async e=>{e.currentTarget.disabled=true;e.currentTarget.textContent='Scanning…';try{let r=await api('/api/media-library/scan',post());notify(r.already_running?'Library scan is already running.':'Library scan started in the background.','ok');mediaLibraryPage=1;mediaLibraryCursors=[null];setTimeout(mediaLibrary,1200)}catch(err){notify(err.message,'error');e.currentTarget.disabled=false}};
  $('#clearMissing').onclick=async()=>{if(!confirm('Remove database entries for media files that no longer exist?'))return;try{await api('/api/media-library/missing',{method:'DELETE'});notify('Missing-file entries cleared.','ok');mediaLibraryPage=1;mediaLibraryCursors=[null];mediaLibrary()}catch(err){notify(err.message,'error')}};
  try{
    let [status,dupes,unmatched]=await Promise.all([api('/api/media-library/status'),api('/api/media-library/duplicates'),api('/api/media-library/unmatched?limit=200&offset=0')]);
    if(view!=='library')return;
    let totalPages=Math.max(1,Math.ceil(status.files/MEDIA_LIBRARY_PAGE_SIZE));
    if(mediaLibraryPage>totalPages){mediaLibraryPage=1;mediaLibraryCursors=[null]}
    $('#libraryStats').innerHTML=[['▶','Files',status.files,'Indexed'],['▱','Storage',bytes(status.total_bytes),'Local media'],['!','Missing',status.missing,'Needs attention'],['≡','Duplicates',status.duplicate_groups,'Fingerprint groups'],['?','Unmatched',status.unmatched,'Needs scene match']].map(x=>`<div class="stat"><div class="stat-icon">${x[0]}</div><div><small>${x[1]}</small><strong>${x[2]}</strong><em>${x[3]}</em></div></div>`).join('');
    await loadMediaLibraryPage(status.files);
    $('#libraryFiles').onclick=async e=>{let page=e.target.closest('[data-library-page]');if(page){let action=page.dataset.libraryPage;if(action==='first'){mediaLibraryPage=1}else if(action==='prev'){mediaLibraryPage=Math.max(1,mediaLibraryPage-1)}else if(action==='next'&&mediaLibraryHasMore){mediaLibraryPage+=1}return mediaLibrary()}let play=e.target.closest('[data-play-media]');if(play)return playMedia(Number(play.dataset.playMedia));let scene=e.target.closest('[data-library-scene]');if(scene)return openLocalScene(Number(scene.dataset.libraryScene));let probe=e.target.closest('[data-probe-media]');if(probe){probe.disabled=true;try{await api(`/api/media-files/${probe.dataset.probeMedia}/probe`,post());notify('Media information refreshed.','ok');mediaLibrary()}catch(err){notify(err.message,'error');probe.disabled=false}return}let fav=e.target.closest('[data-favorite-media]');if(fav){await api(`/api/media-files/${fav.dataset.favoriteMedia}/playback`,patch({favorite:fav.dataset.fav!=='1'}));return mediaLibrary()}};
    $('#libraryDuplicates').innerHTML=dupes.length?dupes.map(g=>`<div class="row"><div class="rowicon">≡</div><div><b>${g.files.length} matching files</b><small>${g.files.map(f=>esc(f.filename)).join('<br>')}</small></div></div>`).join(''):empty('No duplicate fingerprints found.');
    $('#libraryUnmatched').innerHTML=unmatched.filter(x=>!x.missing).length?unmatched.filter(x=>!x.missing).slice(0,30).map(x=>`<div class="row"><div class="rowicon">?</div><div><b>${esc(x.display_name)}</b><small>${esc(x.path)}</small></div><span>${bytes(x.size_bytes)}</span></div>`).join(''):empty('No unmatched files.');
    let tools=status.tools||{};$('#libraryTools').innerHTML=`<div class="row"><div class="rowicon">▶</div><div><b>FFmpeg</b><small>Playback assets and previews</small></div><span class="state ${tools.ffmpeg?'good':'bad'}">${tools.ffmpeg?'Ready':'Missing'}</span></div><div class="row"><div class="rowicon">i</div><div><b>FFprobe</b><small>Media analysis</small></div><span class="state ${tools.ffprobe?'good':'bad'}">${tools.ffprobe?'Ready':'Missing'}</span></div>${status.latest_scan?`<div class="row"><div class="rowicon">↻</div><div><b>Last Scan</b><small>${fmtDate(status.latest_scan.finished_at||status.latest_scan.created_at)}</small></div><span class="state ${status.latest_scan.status==='completed'?'good':status.latest_scan.status==='failed'?'bad':'warn'}">${esc(status.latest_scan.status)}</span></div>`:''}`;
  }catch(e){notify(e.message,'error')}
}