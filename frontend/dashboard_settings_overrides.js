dashboard=async function(){
  $('#app').innerHTML=pageHead('Welcome back','Your downloaded ScarletX library.',`<button class="btn primary" id="addNew">＋ Add New</button>`)+`<div class="stats" id="stats"></div><div class="dashgrid"><div class="panel"><div class="panel-head"><h2>Studios with Recent Releases</h2><button class="linkbtn" data-go="studios">View studios</button></div><div class="rows" id="studioReleaseRows"></div></div><div class="panel"><div class="panel-head"><h2>Upcoming</h2><button class="linkbtn" data-go="calendar">View calendar</button></div><div class="rows" id="calendarRows"></div></div></div><div class="panel recent"><div class="panel-head"><h2>Recently Released Scenes</h2><button class="linkbtn" data-go="library">View library</button></div><div id="recentScenes" style="padding:0 12px 14px"></div></div>`;
  $('#addNew').onclick=()=>{view='scenes';entityMode.scenes='search';nav();renderEntities('scenes')};
  $('#app').onclick=e=>{
    let st=e.target.closest('[data-dashboard-studio]');
    if(st)return studioProfile(st.dataset.dashboardStudio,null);
    let b=e.target.closest('[data-go]');
    if(b){view=b.dataset.go;nav();render()}
  };
  try{
    let [sys,recent,studioData,cal,disk]=await Promise.all([
      api('/api/system/status'),
      api('/api/dashboard/scenes?limit=8'),
      api('/api/dashboard/studios?limit=8'),
      api('/api/calendar?limit=5'),
      api('/api/system/diskspace').catch(()=>[])
    ]);
    if(view!=='dashboard')return;
    let scenes=recent.items||[],studios=studioData.items||[];
    libraryCache=scenes;
    let total=0,used=0;
    disk.filter(x=>x.exists&&x.total_bytes).forEach(x=>{total+=x.total_bytes;used+=x.used_bytes});
    let pct=total?Math.round(used/total*100):0;
    $('#stats').innerHTML=[
      ['▣','Scenes',recent.total||0,'Downloaded','library'],
      ['♙','Performers',sys.performers||0,'In library'],
      ['▥','Studios',sys.studios||0,'In library'],
      ['◎','Wanted',sys.wanted||0,'Missing'],
      ['▱','Storage',total?bytes(used):'—',total?`${pct}% of ${bytes(total)}`:'No scene root yet']
    ].map(x=>`<div class="stat"${x[4]?` data-go="${x[4]}" title="Open Library"`:''}><div class="stat-icon">${x[0]}</div><div><small>${x[1]}</small><strong>${x[2]}</strong><em>${x[3]}</em></div></div>`).join('');
    let sceneStat=[...document.querySelectorAll('#stats .stat')].find(card=>card.querySelector('small')?.textContent==='Scenes');
    if(sceneStat){let detail=sceneStat.querySelector('em');if(detail)detail.textContent='Downloaded'}
    $('#studioReleaseRows').innerHTML=studios.map(x=>`<div class="row"><div class="rowicon studio-logo"><img src="${studioArtUrl(x.tpdb_id||x.id)}" alt="" loading="lazy" onerror="this.remove()"></div><div><button class="studio-link" data-dashboard-studio="${esc(x.tpdb_id||x.id)}">${esc(x.name||'Studio')}</button><small>${esc(x.latest_title||'Latest downloaded release')} · ${fmtDate(x.latest_release_date)}</small></div><span class="badge soft">${Number(x.release_count||0)} ${Number(x.release_count||0)===1?'scene':'scenes'}</span></div>`).join('')||`<div class="row"><div class="rowicon">□</div><div><b>No downloaded studio releases yet</b><small>Studios appear here after scenes are added to the library.</small></div></div>`;
    $('#calendarRows').innerHTML=cal.slice(0,5).map(x=>`<div class="row"><div class="rowicon">${new Date(x.date).getDate()}</div><div><b>${esc(x.title)}</b><small>${fmtDate(x.date)}</small></div><span class="badge soft">Scene</span></div>`).join('')||`<div class="row"><div class="rowicon">□</div><div><b>No upcoming releases</b><small>Monitored release dates will appear here.</small></div></div>`;
    let recentRoot=$('#recentScenes');
    recentRoot.innerHTML=scenes.length?sceneTable(scenes,true):empty('No downloaded scenes yet.');
    bindSceneTableActions(recentRoot,true);
  }catch(err){notify(err.message,'error')}
};

mediaFileRowsHtml=function(files){
  return files.map(x=>{let art=x.scene_id?`/api/artwork/scenes/${encodeURIComponent(x.scene_id)}?size=card`:'';return `<tr data-media-row="${x.id}"><td><div class="library-scene-cell">${art?`<span class="library-scene-thumb"><img src="${esc(art)}" alt="" loading="lazy" onerror="this.closest('.library-scene-thumb').classList.add('missing-art');this.remove()"></span>`:''}<div class="library-scene-copy"><button class="scene-title" data-library-scene="${x.scene_id}">${esc(x.scene_title)}</button><small class="library-studio">${x.studio?`Studio: ${esc(x.studio)}`:'Studio: —'}</small>${x.missing?'<small><span class="state bad">Missing</span></small>':''}</div></div></td><td><div class="media-spec">${x.height?`${x.height}p`:esc(x.quality||'—')} · ${esc(x.video_codec||'—')}</div><small>${durationText(x.duration_seconds)}</small></td><td>${bytes(x.size_bytes)}</td><td>${x.position_seconds?`${durationText(x.position_seconds)} / ${durationText(x.duration_seconds)}`:x.play_count?'Played':'Unwatched'}${x.favorite?'<small>★ Favorite</small>':''}</td><td><div class="actions"><button class="btn small primary" data-play-media="${x.id}" ${x.missing?'disabled':''}>Play</button><button class="btn small" data-probe-media="${x.id}">Refresh</button><button class="btn small" data-favorite-media="${x.id}" data-fav="${x.favorite?'1':'0'}">${x.favorite?'★':'☆'}</button></div></td></tr>`}).join('');
};

const baseRenderSettingsTab=renderSettingsTab;
renderSettingsTab=async function(){
  if(settingsTab!=='general')return baseRenderSettingsTab();
  let s=settingsCache,el=$('#settingsBody');
  el.innerHTML=`<div class="settings-panel"><h2>General</h2><p>ScarletX logging settings.</p><div class="formgrid"><div class="field"><label>Log level</label><select id="logLevel">${['DEBUG','INFO','WARNING','ERROR'].map(x=>`<option ${s.general.log_level===x?'selected':''}>${x}</option>`).join('')}</select></div></div><div class="divider"></div><button class="btn primary" id="saveGeneral">Save</button></div>`;
  $('#saveGeneral').onclick=()=>saveSetting('/api/settings/general',{log_level:val('#logLevel')});
};
