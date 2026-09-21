let view='dashboard', libraryCache=[], settingsCache=null, entityMode={scenes:'library',performers:'library',studios:'library'};
let entityLibraryCache={scenes:null,performers:null,studios:null},entityCursors={scenes:null,performers:null,studios:null},entityTotals={scenes:null,performers:null,studios:null},entityPageSize={scenes:25,performers:25,studios:25};
let entityLibraryQuery={scenes:'',performers:'',studios:''},entityPrefetch=new Map(),entityPage={scenes:1,performers:1,studios:1},entityPageCursors={scenes:[null],performers:[null],studios:[null]};
let entityLibraryFilter={scenes:'monitored',performers:'all',studios:'all'};
let searchChoiceQuery='';
let mediaLibraryRows=[],mediaLibraryCursor=null,mediaLibraryHasMore=false;
let liveQueueFallback=false,liveQueueTimer=null,liveQueueBusy=false,liveQueueSnapshot={tracked:[],clients:{}};
let ACTIVITY_QUEUE_PAGE_SIZE=25;const ACTIVITY_COMPLETED_PAGE_SIZE=20,ACTIVITY_FAILED_PAGE_SIZE=20;
let activityQueuePage=1;
function nav(){$$('#nav button').forEach(b=>b.classList.toggle('active',b.dataset.view===view))}
function sceneImage(x){return x.image_url||x.back_image_url||x.poster_url||x.tpdb_id||x.id||''}
$('#closeModal').onclick=()=>$('#modal').classList.remove('open');$('#modal').onclick=e=>{if(e.target===$('#modal'))$('#modal').classList.remove('open')};
const SFW_MODE_STORAGE_KEY='scarletx-sfw-mode';
function setSfwMode(enabled){
  document.body.classList.toggle('sfw-mode',enabled);
  $('#sfwToggle').setAttribute('aria-pressed',String(enabled));
  $('#sfwToggle').textContent=enabled?'SFW on':'SFW';
  try{localStorage.setItem(SFW_MODE_STORAGE_KEY,enabled?'1':'0');}catch(_){ }
}
let sfwModeEnabled=false;
try{sfwModeEnabled=localStorage.getItem(SFW_MODE_STORAGE_KEY)==='1'}catch(_){ }
setSfwMode(sfwModeEnabled);
$('#sfwToggle').onclick=()=>setSfwMode(!document.body.classList.contains('sfw-mode'));

async function boot(){
  if(window.scarletxInitialView==='settings')view='settings';
  $('#hostLabel').textContent=location.hostname||'local';
  $('#nav').onclick=e=>{let b=e.target.closest('button[data-view]');if(!b)return;view=b.dataset.view;nav();render()};
  $('#queueShortcut').onclick=()=>{view='activity';nav();render()};
  $('#globalSearch').onsubmit=e=>{e.preventDefault();let q=$('#globalSearchInput').value.trim();if(q.length<2)return;searchChoiceQuery=q;view='search-choice';nav();render()};
  try{let s=await api('/api/system/status');$('#versionSide').textContent=`v${s.version} · Local`}catch(e){$('#onlineText').textContent='Offline';$('#statusDot').style.background='#b91c2b'}
  await updateChrome();render();
}
async function updateChrome(){
  try{
    let [a,d]=await Promise.all([api('/api/activity/queue').catch(()=>({tracked:[]})),api('/api/system/diskspace').catch(()=>[])]);
    $('#queueBadge').textContent=(a.tracked||[]).length;
    let x=d.find(i=>i.exists&&i.total_bytes)||d.find(i=>i.exists);
    if(x&&x.total_bytes){let pct=Math.round((x.used_bytes/x.total_bytes)*100);$('#storageBar').style.width=`${pct}%`;$('#storageUsed').textContent=`${bytes(x.used_bytes)} / ${bytes(x.total_bytes)}`;$('#storagePct').textContent=`${pct}%`}
  }catch{}
}
function stopLiveQueue(){if(liveQueueTimer){clearTimeout(liveQueueTimer);liveQueueTimer=null}}
async function render(){nav();if(view==='dashboard')return dashboard();if(view==='library')return mediaLibrary();if(view==='search-choice')return searchChoice();if(['scenes','performers','studios'].includes(view))return renderEntities(view);if(view==='wanted')return wanted();if(view==='activity')return activity();if(view==='calendar')return calendar();if(view==='settings')return settings();if(view==='about')return about()}

function searchChoice(){
  let q=searchChoiceQuery;
  $('#app').innerHTML=pageHead('Choose a search','Search for “'+esc(q)+'” in:')+`<div class="search-choice-grid"><button class="search-choice-card" data-search-choice="performers"><span class="search-choice-icon"><svg data-icon="search-choice-performer" viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="7" r="4"/><path d="M2 21v-2a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v2"/><path d="M16 3.3a4 4 0 0 1 0 7.4M22 21v-2a4 4 0 0 0-3-3.87"/></svg></span><span><b>Performers</b><small>Find a performer to add or monitor</small></span></button><button class="search-choice-card" data-search-choice="scenes"><span class="search-choice-icon"><svg data-icon="search-choice-scene" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8h16v12H4z"/><path d="m4 8 3-5h4L8 8m5 0 3-5h4l-3 5"/><path d="M4 3h16"/></svg></span><span><b>Scenes</b><small>Find a scene to add or monitor</small></span></button><button class="search-choice-card" data-search-choice="studios"><span class="search-choice-icon"><svg data-icon="search-choice-studio" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 21h18M5 21V8l7-5 7 5v13M9 10h2m2 0h2M9 14h2m2 0h2M11 21v-4h2v4"/></svg></span><span><b>Studios</b><small>Find a studio to add or monitor</small></span></button></div>`;
  $$('[data-search-choice]').forEach(button=>button.onclick=()=>{let target=button.dataset.searchChoice;view=target;entityMode[target]='search';nav();renderEntities(target,q)});
}

function about(){
  $('#app').innerHTML=pageHead('About ScarletX','Your local-first media library, built to discover, monitor, and organize your collection.')+`<div class="about-layout"><section class="panel about-intro"><div class="about-mark"><img src="/scarletx-icon.webp?v=approved-20260918-1" alt="ScarletX icon"></div><div><h2>Discover. Monitor. Organize. Enjoy.</h2><p>ScarletX brings your monitored scenes, performers, studios, downloads, and library together in one focused workspace.</p></div></section><div class="about-grid"><section class="panel about-card"><h2>Local-first by design</h2><p>Your library stays on your system. ScarletX connects to the services you choose, while your collection and settings remain under your control.</p></section><section class="panel about-card"><h2>System information</h2><dl class="about-facts"><div><dt>Version</dt><dd id="aboutVersion">Loading…</dd></div><div><dt>Upstream</dt><dd id="aboutUpstream">Loading…</dd></div><div><dt>Runtime</dt><dd>Local</dd></div></dl></section><section class="panel about-card about-agreement-card"><h2>Usage agreement</h2><dl class="about-facts"><div><dt>Status</dt><dd id="aboutAgreementStatus">Loading…</dd></div><div><dt>Accepted</dt><dd id="aboutAgreementDate">Loading…</dd></div><div><dt>Version</dt><dd id="aboutAgreementVersion">Loading…</dd></div></dl><div class="about-links"><a id="aboutAgreementDocument" target="_blank" rel="noopener noreferrer">Usage agreement</a><a id="aboutAgreementLicense" target="_blank" rel="noopener noreferrer">Project license</a><a id="aboutAgreementProject" target="_blank" rel="noopener noreferrer">ScarletX source</a></div></section></div></div>`;
  Promise.all([api('/api/system/status'),api('/api/setup/agreement')]).then(([status,agreement])=>{
    if(view!=='about')return;
    $('#aboutVersion').textContent=status.version||'—';
    $('#aboutUpstream').textContent=status.upstream||'—';
    $('#aboutAgreementStatus').textContent=agreement.accepted?'Accepted':'Not recorded';
    if(agreement.accepted_at){const accepted=new Date(agreement.accepted_at);$('#aboutAgreementDate').textContent=Number.isNaN(accepted.getTime())?agreement.accepted_at:accepted.toLocaleString()}else $('#aboutAgreementDate').textContent='—';
    $('#aboutAgreementVersion').textContent=agreement.version||agreement.current_version||'—';
    $('#aboutAgreementDocument').href=agreement.links?.agreement||'https://github.com/terralayer/ScarletX/blob/main/docs/USAGE-AGREEMENT.md';
    $('#aboutAgreementLicense').href=agreement.links?.license||'https://github.com/terralayer/ScarletX/blob/main/LICENSE';
    $('#aboutAgreementProject').href=agreement.links?.project||'https://github.com/terralayer/ScarletX';
  }).catch(()=>{
    if(view!=='about')return;
    $('#aboutVersion').textContent='Unavailable';$('#aboutUpstream').textContent='Unavailable';$('#aboutAgreementStatus').textContent='Unavailable';$('#aboutAgreementDate').textContent='—';$('#aboutAgreementVersion').textContent='—';
  });
}

function bindDashboardStats(){
  let stats=$('#stats');if(!stats)return;
  stats.querySelectorAll('[data-stat-go]').forEach(button=>{button.onclick=()=>{let target=button.dataset.statGo;if(['scenes','performers','studios'].includes(target))entityMode[target]='library';view=target;nav();render()}});
}
const dashboardIcons = {
    performers: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="7" r="4"/><path d="M4.5 21a7.5 7.5 0 0 1 15 0"/></svg>',
    scenes: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 8h18v12H3z"/><path d="m5 8 2-4h4l-2 4m4 0 2-4h4l-2 4"/><path d="m10 12 5 3-5 3z"/></svg>',
    studios: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 21h18M5 21V8l7-5 7 5v13M9 10h2m2 0h2M9 14h2m2 0h2M11 21v-4h2v4"/></svg>',
    calendar: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4m8-4v4M3 10h18"/></svg>',
    downloads: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m-5-5 5 5 5-5M4 20h16"/></svg>'
  };

  function dashboardStat(icon, label, value, detail, target) {
    return `<button type="button" class="stat dashboard-stat" data-stat-go="${target}"><div class="stat-icon">${icon}</div><div><small>${label}</small><strong>${value}</strong></div><em>${detail}</em></button>`;
  }

  function dashboardStudioName(scene) {
    if (!scene?.studio) return 'Unknown studio';
    return typeof scene.studio === 'string' ? scene.studio : (scene.studio.name || 'Unknown studio');
  }

  function dashboardRecentRows(scenes) {
    if (!scenes.length) return empty('No downloaded scenes yet.');
    return `<div class="approved-recent-list">${scenes.slice(0, 5).map((scene, index) => {
      const localId = scene.id || '';
      const title = scene.title || 'Untitled';
      return `<div class="approved-recent-row text-only" data-dashboard-scene="${esc(localId)}"><div class="approved-recent-copy"><button type="button" class="approved-recent-title" data-dashboard-scene="${esc(localId)}">${esc(title)}</button><div class="approved-recent-meta">${esc(dashboardStudioName(scene))}</div></div><div class="approved-recent-date">${fmtDate(scene.release_date)}${index < 2 ? '<span class="approved-new-badge">NEW</span>' : ''}</div></div>`;
    }).join('')}</div>`;
  }

  function dashboardUpcomingRows(rows) {
    if (!rows.length) return `<div class="row"><div class="rowicon">—</div><div><b>No upcoming releases</b><small>Monitored release dates will appear here.</small></div></div>`;
    return rows.slice(0, 5).map(item => {
      const day = String(item.date || '').slice(8, 10).replace(/^0/, '') || '—';
      return `<div class="row"><div class="rowicon">${esc(day)}</div><div><b title="${esc(item.title || 'Upcoming scene')}">${esc(item.title || 'Upcoming scene')}</b><small>${fmtDate(item.date)}</small></div><span class="badge soft">Scene</span></div>`;
    }).join('');
  }

  async function dashboard(){
    const app = $('#app');
    app.innerHTML = `
      <section class="dashboard-hero">
        <div class="dashboard-hero-copy">
          <h1>Welcome to <span>ScarletX</span></h1>
          <p>Discover. Monitor. Organize. Enjoy.</p>
        </div>
      </section>
      <div class="stats approved-stat-grid" id="stats">
        ${dashboardStat(dashboardIcons.performers, 'Performers', '—', 'Monitored performers', 'performers')}
        ${dashboardStat(dashboardIcons.scenes, 'Scenes', '—', 'In your library', 'library')}
        ${dashboardStat(dashboardIcons.studios, 'Studios', '—', 'Tracked studios', 'studios')}
        ${dashboardStat(dashboardIcons.calendar, 'Upcoming', '—', 'Scenes this month', 'calendar')}
        ${dashboardStat(dashboardIcons.downloads, 'Downloads', '—', 'In progress', 'activity')}
      </div>
      <div class="approved-dashboard-grid">
        <section class="panel recent">
          <div class="panel-head"><h2>Recent Scenes</h2><button class="linkbtn" type="button" data-go="library">View All</button></div>
          <div id="recentScenes"></div>
        </section>
        <section class="panel approved-upcoming">
          <div class="panel-head"><h2>Upcoming Releases</h2><button class="linkbtn" type="button" data-go="calendar">View Calendar</button></div>
          <div class="rows" id="calendarRows"></div>
        </section>
      </div>`;

    bindDashboardStats();

    app.onclick = event => {
      const scene = event.target.closest('[data-dashboard-scene]');
      if (scene) {
        const localId = Number(scene.dataset.dashboardScene || 0);
        if (localId) openLocalScene(localId);
        return;
      }
      const go = event.target.closest('[data-go]');
      if (!go) return;
      const target = go.dataset.go;
      if (['scenes', 'performers', 'studios'].includes(target)) entityMode[target] = 'library';
      view = target;
      nav();
      render();
    };

    try {
      const [sys, recent, cal, queue] = await Promise.all([
        api('/api/system/status'),
        api('/api/dashboard/scenes?limit=8'),
        api('/api/calendar?limit=5&monitored_only=true'),
        api('/api/activity/queue').catch(() => ({tracked: []}))
      ]);
      if (view !== 'dashboard') return;

      const scenes = recent.items || [];
      const calendar = cal || [];
      const downloads = (queue.tracked || []).length;
      libraryCache = scenes;

      $('#stats').innerHTML = [
        dashboardStat(dashboardIcons.performers, 'Performers', sys.performers || 0, 'Monitored performers', 'performers'),
        dashboardStat(dashboardIcons.scenes, 'Scenes', recent.total || 0, 'In your library', 'library'),
        dashboardStat(dashboardIcons.studios, 'Studios', sys.studios || 0, 'Tracked studios', 'studios'),
        dashboardStat(dashboardIcons.calendar, 'Upcoming', calendar.length, 'Scenes this month', 'calendar'),
        dashboardStat(dashboardIcons.downloads, 'Downloads', downloads, 'In progress', 'activity')
      ].join('');
      bindDashboardStats();

      $('#recentScenes').innerHTML = dashboardRecentRows(scenes);
      $('#calendarRows').innerHTML = dashboardUpcomingRows(calendar);
      $('#queueBadge').textContent = downloads;
    } catch (error) {
      if (view !== 'dashboard') return;
      notify(error.message, 'error');
    }
  };
function performerLinks(x){
  let rows=x.performers||[];
  return rows.length?`<div class="credit-links">${rows.map(p=>`<button class="person-link" data-performer-link="${esc(p.id||p.tpdb_id||'')}" data-performer-local-id="${esc(p.local_id||'')}" title="Open performer profile">${esc(p.name||'Performer')}</button>`).join('')}</div>`:'<span class="muted">—</span>';
}
function studioLink(x,includeDate=true){
  let st=x.studio,date=includeDate?`<small class="studio-release">${fmtDate(x.release_date)}</small>`:'';
  if(!st)return `<span class="studio-credit"><span class="muted">—</span>${date}</span>`;
  let name=typeof st==='string'?st:(st.name||'Studio'),id=typeof st==='object'?(st.id||st.tpdb_id||''):(x.studio_id||'');
  return `<span class="studio-credit"><span class="studio-copy">${id?`<button class="studio-link" data-studio-link="${esc(id)}">${esc(name)}</button>`:esc(name)}${date}</span></span>`;
}
function sceneRowsHtml(rows,inLibrary=false,releaseDateUnderScene=false){
  return rows.map(x=>{
    let id=x.tpdb_id||x.id,local=inLibrary?x.id:(x.local_id||''),mediaId=x.media_id||(x.files||[])[0]?.id||'',hasFile=!!mediaId||inLibrary&&(x.has_file||(x.files||[]).length>0);
    let monitoringKnown=inLibrary||typeof x.monitored==='boolean';
    let downloadStatus=hasFile?'Downloaded':(inLibrary?'':x.download_status||'Available');
    let status=monitoringKnown?`<span class="state ${x.monitored?'good':'warn'}">${x.monitored?'Monitored':'Not monitored'}</span>`:'';
    if(!monitoringKnown||(downloadStatus&&!['Available','Monitored','In library'].includes(downloadStatus))){
      status+=`<span class="state ${['Downloaded','Downloading','Queued','Post-processing','Import pending'].includes(downloadStatus)?'good':downloadStatus==='Failed'?'bad':'warn'}">${esc(downloadStatus)}</span>`;
    }
    let sceneCopy=releaseDateUnderScene?`<div class="dashboard-scene-copy"><button class="scene-title" data-scene-detail>${esc(x.title||'Untitled')}</button><div class="dashboard-release-date">${fmtDate(x.release_date)}</div></div>`:`<button class="scene-title" data-scene-detail>${esc(x.title||'Untitled')}</button>`;
    return `<tr data-scene-id="${esc(id)}" data-local-id="${esc(local)}"><td><div class="scene-credit">${sceneCopy}</div></td><td>${studioLink(x,!releaseDateUnderScene)}</td><td>${performerLinks(x)}</td><td><div class="scene-status">${status}</div></td><td><div class="actions"><button class="btn small primary" data-play-scene="${esc(mediaId)}" ${mediaId?'':'disabled title="Not downloaded"'}>▶ Play</button>${!x.monitored?'<button class="btn small primary" data-monitor-scene>Monitor</button>':''}${inLibrary?'<button class="btn small danger" data-remove-scene>Remove</button>':'<button class="btn small" data-scene-detail>Details</button>'}</div></td></tr>`;
  }).join('');
}
function sceneTable(rows,inLibrary=false,releaseDateUnderScene=false){if(!rows.length)return empty('No scenes found.');return `<div class="tablewrap"><table class="table"><thead><tr><th>Scene</th><th>Studio</th><th>Performers</th><th>Status</th><th></th></tr></thead><tbody>${sceneRowsHtml(rows,inLibrary,releaseDateUnderScene)}</tbody></table></div>`}
function bindSceneTableActions(root,inLibrary){
  if(!root)return;root.onclick=async e=>{
    let p=e.target.closest('[data-performer-link]');if(p)return performerProfile(p.dataset.performerLink,p.dataset.performerLocalId||null);
    let st=e.target.closest('[data-studio-link]');if(st)return studioProfile(st.dataset.studioLink,null);
    let tr=e.target.closest('tr[data-scene-id]');if(!tr)return;let id=tr.dataset.sceneId,local=tr.dataset.localId;
    let b=e.target.closest('button');if(!b)return;
    try{
      if(b.hasAttribute('data-play-scene'))return playMedia(Number(b.dataset.playScene));
      if(b.hasAttribute('data-monitor-scene')){b.disabled=true;b.textContent='Starting…';await api(inLibrary?`/api/library/scenes/${local}/monitor`:`/api/metadata/scenes/${encodeURIComponent(id)}/monitor`,post());b.remove();notify('Monitored. ScarletX is searching and downloading in the background.','ok');return}
      if(b.hasAttribute('data-remove-scene')){if(!confirm('Remove this scene from ScarletX?'))return;await api(`/api/library/scenes/${local}`,{method:'DELETE'});let cursor=entityPageCursors.scenes[entityPage.scenes-1]||null;return loadEntityLibrary('scenes',cursor)}
      if(b.hasAttribute('data-scene-detail'))return scenePage(id,inLibrary?local:null);
    }catch(err){notify(err.message,'error');b.disabled=false;b.textContent='Monitor'}
  }
}

async function renderEntities(type,forcedQuery=''){
  // Only an explicit search opens search mode; sidebar/back navigation opens the library.
  let mode=forcedQuery?'search':'library';entityMode[type]=mode;let names={scenes:'Scenes',performers:'Performers',studios:'Studios'};let singular={scenes:'scene',performers:'performer',studios:'studio'}[type];
  let filterOptions=type==='performers'?[['all','All'],['female','Female'],['male','Male']]:type==='scenes'?[['all','All'],['downloaded','Downloaded'],['monitored','Monitored']]:[];
  let libraryFilters=mode==='library'&&filterOptions.length?`<div class="tabs entity-filters">${filterOptions.map(([value,label])=>`<button data-library-filter="${value}" class="${entityLibraryFilter[type]===value?'active':''}">${label}</button>`).join('')}</div>`:'';
  let pageSizePicker=mode==='library'?`<label class="entity-page-size" title="Rows shown per page"><span>Show</span><select id="entityPageSize" aria-label="Rows per page">${[25,50,100].map(size=>`<option value="${size}" data-page-size="${size}" ${entityPageSize[type]===size?'selected':''}>${size}</option>`).join('')}</select><span>rows</span></label>`:'';
  $('#app').innerHTML=pageHead(names[type],'',pageSizePicker)+`<div class="toolbar">${libraryFilters}${mode==='library'&&type==='scenes'?`<button class="btn" id="refreshAll">Refresh Library</button>`:''}</div><div id="entityNotice"></div><div id="entityPaginationTop"></div><div class="${type==='scenes'?'':'cardgrid'}" id="entityGrid"></div>`;
  $$('[data-library-filter]').forEach(b=>b.onclick=()=>{entityLibraryFilter[type]=b.dataset.libraryFilter;entityLibraryCache[type]=null;entityCursors[type]=null;entityTotals[type]=null;entityPage[type]=1;entityPageCursors[type]=[null];renderEntities(type)});
  if($('#entityPageSize'))$('#entityPageSize').onchange=e=>{let b=e.currentTarget;entityPageSize[type]=Number(b.value);entityLibraryCache[type]=null;entityCursors[type]=null;entityTotals[type]=null;entityPage[type]=1;entityPageCursors[type]=[null];entityPrefetch.clear();renderEntities(type)};
  if($('#refreshAll'))$('#refreshAll').onclick=async()=>{let button=$('#refreshAll');button.disabled=true;try{let result=await api('/api/library/scenes/refresh',post());notify(result.already_running?'Library refresh is already running.':'Library refresh started and will run safely in the background.','ok')}catch(error){notify(error.message,'error')}finally{button.disabled=false}};
  if(mode==='library'&&!forcedQuery){let cached=entityLibraryCache[type];if(cached)paintEntityLibrary(type,cached,false);else $('#entityGrid').innerHTML=empty(`Loading ${type}…`);let cursor=entityPageCursors[type][entityPage[type]-1]||null;return loadEntityLibrary(type,cursor,false)}if(forcedQuery)return searchEntity(type,forcedQuery);$('#entityGrid').innerHTML=empty(`Search TPDB to add a ${singular}.`)
}
function entityPager(type,total,hasMore){let page=entityPage[type],size=entityPageSize[type];if(page===1&&!hasMore&&Number(total||0)<=size)return'';let numbers=Array.from({length:page},(_,i)=>i+1).filter(n=>page<=7||n===1||Math.abs(n-page)<=1).map(n=>`<button class="btn small" data-entity-page="${n}" ${n===page?'disabled':''}>${n}</button>`).join('');return `<div class="pagination-bar entity-pagination"><button class="btn small" data-entity-page="prev" ${page===1?'disabled':''}>Previous</button>${numbers}<button class="btn small" data-entity-page="next" ${!hasMore?'disabled':''}>Next</button></div>`}
function bindEntityPager(type,data){
  const grid=$('#entityGrid'),top=$('#entityPaginationTop'),sourcePage=entityPage[type];
  const buttons=[...(top?.querySelectorAll('[data-entity-page]')||[]),...(grid?.querySelectorAll('[data-entity-page]')||[])];
  buttons.forEach(button=>button.onclick=()=>{
    if(button.disabled||entityPage[type]!==sourcePage)return false;
    const action=button.dataset.entityPage,target=action==='prev'?Math.max(1,sourcePage-1):action==='next'&&data.has_more?sourcePage+1:Number(action);
    const cursor=entityPageCursors[type][target-1]||null;
    if(target>1&&!cursor)return false;
    return changeListPage({host:grid,page:target,getPage:()=>entityPage[type],setPage:value=>entityPage[type]=value,
      load:()=>loadEntityLibrary(type,cursor,false),current:()=>$('#entityGrid')===grid&&view===type,scrollTarget:$('#app')});
  });
}
function paintEntityLibrary(type,data,append=false){
  let rows=data.items||[],grid=$('#entityGrid');if(!grid)return;
  grid.querySelector('.load-more')?.remove();
  if(type==='scenes'){
    if(append&&grid.querySelector('tbody')){grid.querySelector('tbody').insertAdjacentHTML('beforeend',sceneRowsHtml(rows,true));libraryCache.push(...rows)}
    else{libraryCache=[...rows];grid.innerHTML=sceneTable(rows,true);bindSceneTableActions(grid,true)}
  }else{
    if(append&&grid.querySelector('.media-card'))grid.insertAdjacentHTML('beforeend',rows.map(x=>entityCard(type,x,true)).join(''));
    else grid.innerHTML=rows.length?rows.map(x=>entityCard(type,x,true)).join(''):empty(`No ${type} in your library yet.`);
    bindEntityActions(type,true);
  }
  let knownTotal=entityLibraryCache[type]?.total??entityTotals[type]??null,cache=entityLibraryCache[type]||{items:[]};if(append)cache.items=[...(cache.items||[]),...rows];else cache={...data,items:[...rows]};cache.next_cursor=data.next_cursor;cache.has_more=!!data.has_more;cache.total=data.total??knownTotal??rows.length;entityLibraryCache[type]=cache;entityCursors[type]=data.next_cursor||null;entityTotals[type]=cache.total;
  let total=cache.total,pager=entityPager(type,total,!!data.has_more),top=$('#entityPaginationTop');
  if(top)top.innerHTML=pager;
  grid.insertAdjacentHTML('beforeend',pager);
  bindEntityPager(type,data);
}
function entityPageUrl(type,cursor=null,q=''){
  let size=entityPageSize[type],filter=entityLibraryFilter[type]||'all',filterKey=type==='performers'?'gender':type==='scenes'?'status':'',scope=['performers','studios'].includes(type)?'&monitored_only=true':'';return `/api/library/${type}/page?limit=${size}${scope}`+(cursor?`&cursor=${encodeURIComponent(cursor)}`:'')+(q?`&q=${encodeURIComponent(q)}`:'')+(filterKey&&filter!=='all'?`&${filterKey}=${encodeURIComponent(filter)}`:'');
}
function prefetchEntityPage(type,cursor,q=''){
  if(!cursor)return;let url=entityPageUrl(type,cursor,q);if(entityPrefetch.has(url))return;
  let run=()=>{if(!entityPrefetch.has(url))entityPrefetch.set(url,api(url).catch(err=>{entityPrefetch.delete(url);throw err}))};
  if('requestIdleCallback'in window)requestIdleCallback(run,{timeout:700});else setTimeout(run,80);
}
async function loadEntityLibrary(type,cursor=null,append=false,q=null){
  try{
    if(q===null)q=entityLibraryQuery[type]||'';if(!append)entityLibraryQuery[type]=q;
    let url=entityPageUrl(type,cursor,q),pending=entityPrefetch.get(url),data=pending?await pending:await api(url);entityPrefetch.delete(url);
    if(view!==type)return false;
    entityPageCursors[type][entityPage[type]]=data.next_cursor||null;
    paintEntityLibrary(type,data,append);if(data.has_more&&data.next_cursor)prefetchEntityPage(type,data.next_cursor,q);
    return true
  }catch(e){notify(e.message,'error');return false}
}
// Entity search is owned by entity_search.js.
function entityCard(type,x,inLibrary){
  let id=x.tpdb_id||x.id, img=x.image_url||x.poster_url||x.logo_url||'', title=x.title||x.name||'Untitled',sub=x.aliases||x.description||'';
  let posterClass=type==='performers'?'media-poster performer-poster':'media-poster';
  let cachedImg=type==='performers'?`/api/artwork/performers/${encodeURIComponent(id)}?size=card`:type==='studios'?studioArtUrl(id):img;
  let renderImg=type==='studios'||!!img;
  let actions=inLibrary?`${type==='performers'?`<button class="btn small ${x.monitored?'':'primary'}" data-toggle-monitor data-monitored="${x.monitored?'true':'false'}">${x.monitored?'Unmonitor':'Monitor'}</button>`:''}<button class="btn small" data-detail>Details</button>`:`<button class="btn small" data-add-only>Add</button><button class="btn small primary" data-add-monitor>Add & Monitor</button><button class="btn small" data-remote-detail>Details</button>`;
  let actionClass=type==='performers'?'actions performer-card-actions':'actions';
  let footer=type==='studios'&&inLibrary?`<div class="studio-card-footer"><div class="actions">${actions}</div><span class="studio-scene-count" title="Downloaded / total scenes">${Number(x.downloaded_scene_count||0)} / ${Number(x.scene_count||0)} scenes</span></div>`:`<div class="${actionClass}">${actions}</div>`;
  return `<article class="media-card ${type==='performers'?'performer-card':type==='studios'?'studio-card':''}" data-id="${esc(id)}" data-local-id="${inLibrary?esc(x.id):''}"><div class="${posterClass}">${renderImg?`<img src="${esc(cachedImg)}" loading="lazy" ${type==='performers'?'data-performer-image title="Open performer profile"':''} onerror="this.remove()">`:''}</div><div class="media-body"><h3>${esc(title)}</h3>${inLibrary?`<small class="state ${x.monitored?'good':'warn'}" data-entity-status>Status: ${x.monitored?'Monitored':'Not monitored'}</small>`:''}<p>${esc(typeof sub==='string'?sub:'')}</p>${footer}</div></article>`
}
function bindEntityActions(type,inLibrary){
  $('#entityGrid').onclick=async e=>{let c=e.target.closest('.media-card');if(!c)return;let b=e.target.closest('button'),id=c.dataset.id,local=c.dataset.localId;
    if(!b&&type==='performers')return performerProfile(id,local||null);
    if(!b&&type==='studios')return studioProfile(id,local||null);
    if(!b)return;
    try{
      if(b.hasAttribute('data-add-only')||b.hasAttribute('data-add-monitor')){let monitored=b.hasAttribute('data-add-monitor');let buttons=[...c.querySelectorAll('[data-add-only],[data-add-monitor]')];buttons.forEach(x=>x.disabled=true);b.textContent=monitored?'Adding & Monitoring…':'Adding…';let r=await api(`/api/library/${type}/${encodeURIComponent(id)}`,post({monitored}));if(type==='performers'){entityMode[type]='library';entityLibraryCache[type]=null;entityCursors[type]=null;entityTotals[type]=null;view=type;nav();notify(`Performer added. Metadata caching started${r.job_id?` (job ${r.job_id})`:''}${monitored?' and monitoring is enabled.':'.'}`,'ok');return renderEntities(type)}entityMode[type]='search';b.textContent=monitored?'Added & Monitoring ✓':'Added ✓';notify(`${type==='studios'?'Studio':'Performer'} added. Metadata caching started${r.job_id?` (job ${r.job_id})`:''}${monitored?' and monitoring is enabled.':'.'}`,'ok');return}
      if(b.hasAttribute('data-toggle-monitor')){let monitored=b.dataset.monitored==='true';let next=await toggleEntityMonitor(type,local,monitored,b);b.dataset.monitored=String(next);let status=c.querySelector('[data-entity-status]');if(status){status.className=`state ${next?'good':'warn'}`;status.textContent=`Status: ${next?'Monitored':'Not monitored'}`}return}
      if(b.hasAttribute('data-detail'))return type==='performers'?performerProfile(id,local):type==='studios'?studioProfile(id,local):localDetail(type,local);
      if(b.hasAttribute('data-remote-detail'))return type==='performers'?performerProfile(id,null):type==='studios'?studioProfile(id,null):remoteDetail(type,id);
    }catch(err){notify(err.message,'error');b.disabled=false}
  }
}

async function monitorAllEntity(type,id,localId,button){
  button.disabled=true;button.textContent='Monitoring All…';
  try{let r=localId?await api(`/api/library/${type}/${localId}/monitor`,patch({monitored:true})):await api(`/api/library/${type}/${encodeURIComponent(id)}`,post({monitored:true}));button.textContent='Monitor All ✓';notify(`Monitor All started${r.job_id?` (job ${r.job_id})`:''}. ScarletX is searching every eligible studio scene and will download the best matches.`,'ok');return r}catch(e){button.disabled=false;button.textContent='Monitor All';throw e}
}
async function toggleEntityMonitor(type,localId,monitored,button){
  button.disabled=true;button.textContent=monitored?'Unmonitoring…':'Monitoring…';
  try{let result=await api(`/api/library/${type}/${encodeURIComponent(localId)}/monitor`,patch({monitored:!monitored}));button.textContent=monitored?'Monitor':'Unmonitor';button.disabled=false;notify(`${type==='performers'?'Performer':'Studio'} ${monitored?'unmonitored':'monitored'}.`,'ok');if(button.isConnected&&button.id==='togglePerformerMonitor')performerProfile(result.tpdb_id,localId);if(button.isConnected&&button.id==='toggleStudioMonitor')studioProfile(result.tpdb_id,localId);return !monitored}catch(e){button.disabled=false;button.textContent=monitored?'Unmonitor':'Monitor';throw e}
}
function sceneProfileList(rows){
  if(!rows.length)return empty('No scenes found.');
  let groups=new Map();
  rows.forEach(scene=>{let year=String(scene.release_date||'').slice(0,4)||'Unknown year';if(!groups.has(year))groups.set(year,[]);groups.get(year).push(scene)});
  return '<p class="muted">All scenes — monitored and unmonitored.</p>'+[...groups.entries()].sort(([a],[b])=>{if(a==='Unknown year')return 1;if(b==='Unknown year')return -1;return Number(b)-Number(a)}).map(([year,scenes],index)=>`
    <details class="profile-year" ${index===0?'open':''}>
      <summary class="profile-year-header">
        <span class="profile-year-icon" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M16 3v4M8 3v4M3 11h18M8 15h2M14 15h2"/></svg></span>
        <span class="profile-year-label">${esc(year)}</span>
        <span class="profile-year-count">${scenes.length} scene${scenes.length===1?'':'s'}</span>
        <span class="profile-year-chevron" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false"><path d="m9 5 7 7-7 7"/></svg></span>
      </summary>
      <div class="profile-year-content">${sceneTable(scenes,false)}</div>
    </details>`).join('');
}
function bindProfileSceneLinks(root){bindSceneTableActions(root,false)}

function numericPart(v){let m=String(v??'').replace(/,/g,'.').match(/-?\d+(?:\.\d+)?/);return m?Number(m[0]):null}
function trimNum(v,d=0){return Number(v).toFixed(d).replace(/\.0+$/,'')}
function usHeight(v){if(v===null||v===undefined||String(v).trim()==='')return null;let raw=String(v).trim().toLowerCase(),cm=null,inches=null;let feet=raw.match(/(\d+)\s*['′]\s*(\d+(?:\.\d+)?)?/);if(feet){inches=Number(feet[1])*12+Number(feet[2]||0);cm=inches*2.54}else{let n=numericPart(raw);if(n===null)return v;if(/\bcm\b/.test(raw)||n>100)cm=n;else if(/\bm\b/.test(raw)&&n<3)cm=n*100;else if(/in|inch|"|″/.test(raw)||n>=48)inches=n;else cm=n;if(inches===null)inches=cm/2.54;if(cm===null)cm=inches*2.54}let ft=Math.floor(inches/12),inch=Math.round(inches-ft*12);if(inch===12){ft++;inch=0}return `${ft}'${inch}" (${Math.round(cm)} cm)`}
function usWeight(v){if(v===null||v===undefined||String(v).trim()==='')return null;let raw=String(v).trim().toLowerCase(),n=numericPart(raw);if(n===null)return v;let kg,lb;if(/lb|pound/.test(raw)){lb=n;kg=lb/2.2046226218}else{kg=n;lb=kg*2.2046226218}return `${Math.round(lb)} lb (${trimNum(kg,1)} kg)`}
function usLength(v){if(v===null||v===undefined||String(v).trim()==='')return null;let raw=String(v).trim().toLowerCase(),n=numericPart(raw);if(n===null)return v;let inch,cm;if(/cm/.test(raw)||n>50){cm=n;inch=cm/2.54}else{inch=n;cm=inch*2.54}return `${trimNum(inch,1)} in (${Math.round(cm)} cm)`}
function usMeasurements(v){if(v===null||v===undefined||String(v).trim()==='')return null;let raw=String(v).trim(),nums=[...raw.matchAll(/\d+(?:\.\d+)?/g)].map(m=>Number(m[0]));if(nums.length<3)return raw;let metric=nums.some(n=>n>55),us=metric?nums.map(n=>n/2.54):nums,cm=metric?nums:nums.map(n=>n*2.54);return `${us.slice(0,3).map(n=>trimNum(n,1)).join('-')} in (${cm.slice(0,3).map(n=>Math.round(n)).join('-')} cm)`}
function performerFacts(x,monitored=null){
  let facts=[];let add=(label,value)=>{if(value!==null&&value!==undefined&&String(value).trim()!=='')facts.push(`<div class="profile-fact"><b>${esc(label)}</b><span>${esc(value)}</span></div>`)};
  if(monitored!==null)add('Monitored',monitored?'Yes':'No');
  add('Status',x.status||((x.deathday)?'Deceased':(x.career_end_year?'Retired':(x.career_start_year?'Active':'Unknown'))));
  add('Age',x.age);add('Born',x.birthday?fmtDate(x.birthday):null);
  add('Measurements',usMeasurements(x.measurements));add('Cup size',x.cup_size);
  add('Breasts',x.fake_boobs===true?'Enhanced / Fake':x.fake_boobs===false?'Natural':null);
  add('Waist',usLength(x.waist));add('Hips',usLength(x.hips));add('Height',usHeight(x.height));add('Weight',usWeight(x.weight));
  add('Ethnicity',x.ethnicity);add('Nationality',x.nationality);add('Birthplace',x.birthplace);
  add('Hair',x.hair_color);add('Eyes',x.eye_color);add('Astrology',x.astrology);
  add('Career',x.career_start_year?`${x.career_start_year} – ${x.career_end_year||'Present'}`:null);
  add('Tattoos',x.tattoos);add('Piercings',x.piercings);
  add('Aliases',(x.aliases||[]).join(', '));
  return facts.join('');
}
function performerDetailBody(x,id,monitored=null){let img=x.image_url?`/api/artwork/performers/${encodeURIComponent(id)}`:'';return `<div class="performer-detail"><div class="performer-full-image">${img?`<img src="${esc(img)}" alt="${esc(x.name||'Performer')}" loading="eager" onerror="this.remove()">`:'No performer image available.'}</div><div><div class="profile-facts">${performerFacts(x,monitored)}</div><div class="divider"></div><p class="profile-bio">${esc(x.bio||'No biography available.')}</p></div></div>`}
async function loadAllPerformerScenes(id,localId=null){
  let items=[],page=1,total=0;
  while(page<=1000){let url=localId?`/api/library/performers/${encodeURIComponent(localId)}/scenes?page=${page}&per_page=100`:`/api/metadata/performers/${encodeURIComponent(id)}/scenes?page=${page}&per_page=100`;let result=await api(url);let rows=result.items||[];items.push(...rows);total=Number(result.total||items.length);if(page*Number(result.per_page||100)>=total)break;page++}
  return {items,total:items.length};
}
async function loadAllStudioScenes(id,localId=null){
  let items=[],page=1,total=0;
  while(page<=1000){let url=localId?`/api/library/studios/${encodeURIComponent(localId)}/scenes?page=${page}&per_page=100`:`/api/metadata/studios/${encodeURIComponent(id)}/scenes?page=${page}&per_page=100`;let result=await api(url);let rows=result.items||[];items.push(...rows);total=Number(result.total||items.length);if(page*Number(result.per_page||100)>=total)break;page++}
  return {items,total:items.length};
}
function localPerformerProfile(x){let aliases=x.aliases;if(typeof aliases==='string')aliases=aliases.split(',').map(v=>v.trim()).filter(Boolean);let links=x.links||{};return {...x,id:x.tpdb_id,aliases:aliases||[],links};}

async function performerProfile(id,localId=null){
  const generation=nextNavigationGeneration();
  $('#app').innerHTML=pageHead('Performer','Loading performer profile…',`<button class="btn" id="backPerformers">← Performers</button>`)+`<div class="empty">Loading performer information…</div>`;
  $('#backPerformers').onclick=()=>{view='performers';renderEntities('performers')};
  try{
    let local=null;
    if(localId){try{local=await api(`/api/library/performers/${encodeURIComponent(localId)}/detail`)}catch(_){}}
    else{let cached=entityLibraryCache.performers?.items||[],summary=cached.find(v=>String(v.tpdb_id)===String(id))||null;if(summary?.id){try{local=await api(`/api/library/performers/${encodeURIComponent(summary.id)}/detail`)}catch(_){local=summary}}}
    let resolvedLocalId=localId||local?.id||null;
    let x=local?localPerformerProfile(local):await api(`/api/metadata/performers/${encodeURIComponent(id)}`);
    // Paint the profile as soon as its own record is available.  A performer can
    // have hundreds of scenes, so fetching every page before rendering made the
    // whole screen feel stalled.
    let scenes={items:[]},scenesPromise=loadAllPerformerScenes(id,resolvedLocalId).catch(()=>scenes);
    let img=x.image_url?`/api/artwork/performers/${encodeURIComponent(id)}`:'';let links=Object.entries(x.links||{}).filter(([,v])=>v).map(([k,v])=>`<a class="btn small" target="_blank" rel="noopener" href="${esc(v)}">${esc(k)}</a>`).join('');
    if(!navigationGenerationCurrent(generation))return;$('#app').innerHTML=pageHead(x.name||'Performer','Cached performer profile',`<button class="btn" id="backPerformers">← Performers</button>${local?.monitored?'':`<button class="btn primary" id="monitorAllPerformer">Monitor All</button>`}`)+`<div class="profile-shell"><div class="profile-image">${img?`<img src="${esc(img)}" alt="${esc(x.name||'Performer')}" loading="eager" onerror="this.remove()">`:'No performer image available.'}</div><div><div class="profile-facts">${performerFacts(x,local?local.monitored:null)}</div>${x.bio?`<div class="profile-section"><h2>Biography</h2><div class="profile-bio">${esc(x.bio)}</div></div>`:''}${links?`<div class="profile-section"><h2>Links</h2><div class="profile-links">${links}</div></div>`:''}</div></div><div class="profile-section"><h2>Studio Scenes</h2><div id="performerSceneList">${sceneProfileList(scenes.items||[])}</div></div>`;
    $('#backPerformers').onclick=()=>{view='performers';renderEntities('performers')};if($('#monitorAllPerformer'))$('#monitorAllPerformer').onclick=async e=>{try{await monitorAllEntity('performers',id,resolvedLocalId,e.currentTarget)}catch(err){notify(err.message,'error')}};
    scenesPromise.then(rows=>{if(!navigationGenerationCurrent(generation))return;let list=$('#performerSceneList');if(!list)return;list.innerHTML=sceneProfileList(rows.items||[]);bindProfileSceneLinks(list)});
  }catch(e){if(!navigationGenerationCurrent(generation))return;notify(e.message,'error');if(!navigationGenerationCurrent(generation))return;$('#app').innerHTML=pageHead('Performer','Unable to load performer profile.',`<button class="btn" id="backPerformers">← Performers</button>`)+empty(e.message);$('#backPerformers').onclick=()=>{view='performers';renderEntities('performers')}}
}

async function studioProfile(id,localId=null){
  const generation=nextNavigationGeneration();
  $('#app').innerHTML=pageHead('Studio','Loading studio…',`<button class="btn" id="backStudios">← Studios</button>`)+empty('Loading studio information…');
  $('#backStudios').onclick=()=>{view='studios';renderEntities('studios')};
  try{
    let local=null;
    if(localId){try{local=await api(`/api/library/studios/${encodeURIComponent(localId)}/detail`)}catch(_){}}
    else{let cached=entityLibraryCache.studios?.items||[],summary=cached.find(v=>String(v.tpdb_id)===String(id))||null;if(summary?.id){try{local=await api(`/api/library/studios/${encodeURIComponent(summary.id)}/detail`)}catch(_){local=summary}}}
    let resolvedLocalId=localId||local?.id||null;
    let x=local?{...local,id:local.tpdb_id}:await api(`/api/metadata/studios/${encodeURIComponent(id)}`);
    let scenes={items:[]};try{scenes=await loadAllStudioScenes(id,resolvedLocalId)}catch(_){}
    if(!navigationGenerationCurrent(generation))return;$('#app').innerHTML=pageHead(x.name||'Studio','Cached studio profile',`<button class="btn" id="backStudios">← Studios</button>${local?.monitored?'':`<button class="btn primary" id="monitorAllStudio">Monitor All</button>`}`)+`<div class="profile-facts"><div class="profile-fact"><b>Monitored</b><span>${local?.monitored?'Yes':'No'}</span></div>${x.url?`<div class="profile-fact"><b>Website</b><span><a target="_blank" rel="noopener" href="${esc(x.url)}">Open site</a></span></div>`:''}</div>${x.description?`<div class="profile-section"><h2>About</h2><div class="profile-bio">${esc(x.description)}</div></div>`:''}<div class="profile-section"><h2>Studio Scenes</h2><div id="studioSceneList">${sceneProfileList(scenes.items||[])}</div></div>`;
    $('#backStudios').onclick=()=>{view='studios';renderEntities('studios')};if($('#monitorAllStudio'))$('#monitorAllStudio').onclick=async e=>{try{await monitorAllEntity('studios',id,resolvedLocalId,e.currentTarget)}catch(err){notify(err.message,'error')}};bindProfileSceneLinks($('#studioSceneList'));
  }catch(e){if(!navigationGenerationCurrent(generation))return;notify(e.message,'error');if(!navigationGenerationCurrent(generation))return;$('#app').innerHTML=pageHead('Studio','Unable to load studio.',`<button class="btn" id="backStudios">← Studios</button>`)+empty(e.message);$('#backStudios').onclick=()=>{view='studios';renderEntities('studios')}}
}


async function openLocalScene(localId){
  const generation=nextNavigationGeneration();
  try{let x=await api(`/api/library/scenes/${encodeURIComponent(localId)}/detail`);if(!navigationGenerationCurrent(generation))return;return scenePage(x.tpdb_id,localId)}catch(e){notify(e.message,'error')}
}
async function scenePage(id,localId=null){
  const generation=nextNavigationGeneration();
  let local=null,remote=null;
  try{
    if(localId){try{local=await api(`/api/library/scenes/${encodeURIComponent(localId)}/detail`)}catch(_){local=null}}
    if(!local){try{remote=await api(`/api/metadata/scenes/${encodeURIComponent(id)}`)}catch(_){remote=null}}
    let x=local||remote||{},files=local?.files||[];
    let mediaRows=local?.files||[];
    let firstMedia=mediaRows.find(media=>!media.missing),hero=id?`/api/artwork/scenes/${encodeURIComponent(id)}`:'',fallbackHero=firstMedia?`/api/media-files/${firstMedia.id}/screengrab`:'';
    let studio=x.studio?.name||local?.studio||'—',studioId=x.studio?.id||local?.studio_id,studioLocalId=x.studio?.local_id||local?.studio_local_id||null;
    let perf=x.performers||local?.performers||[];
    let sceneInfoPlay=`<div class="scene-info-actions"><button class="btn primary" id="playSceneInfo" ${firstMedia?'':'disabled title="Not downloaded"'}>▶ Play</button></div>`;
    if(!navigationGenerationCurrent(generation))return;$('#app').innerHTML=pageHead(x.title||'Scene','',`<button class="btn" id="backScenes">← Scenes</button>${local?.monitored?'':`<button class="btn primary" id="monitorScenePage">Monitor</button>`}${firstMedia?`<button class="btn primary" id="playScenePage">Play</button>`:''}`)+`<div class="profile-shell"><div class="profile-image">${hero?`<img src="${esc(hero)}" alt="${esc(x.title||'Scene')}" loading="eager" data-fallback-hero="${esc(fallbackHero)}" onerror="if(this.dataset.fallbackHero){this.onerror=null;this.src=this.dataset.fallbackHero}else{this.remove()}">`:fallbackHero?`<img src="${esc(fallbackHero)}" alt="${esc(x.title||'Scene')}" loading="eager" onerror="this.remove()">`:'No scene artwork available.'}</div><div><div class="profile-facts"><div class="profile-fact"><b>Studio</b><span>${studioId?`<button class="credit-link" data-scene-studio="${esc(studioId)}">${esc(studio)}</button>`:esc(studio)}</span></div><div class="profile-fact"><b>Release</b><span>${fmtDate(x.release_date)}</span></div><div class="profile-fact"><b>Runtime</b><span>${durationText(x.duration)}</span></div><div class="profile-fact"><b>Status</b><span>${firstMedia?'Downloaded':local?.monitored?'Monitored':'Available'}</span></div><div class="profile-fact"><b>Files</b><span>${mediaRows.length||files.length||0}</span></div></div>${sceneInfoPlay}${x.description?`<div class="profile-section"><h2>Description</h2><div class="profile-bio">${esc(x.description)}</div></div>`:''}<div class="profile-section"><h2>Performers</h2><div class="profile-links">${perf.length?perf.map(p=>`<button class="credit-link" data-scene-performer="${esc(p.id)}">${esc(p.name)}</button>`).join(' '):'—'}</div></div>${x.tags?.length?`<div class="profile-section"><h2>Tags</h2><div class="profile-links">${x.tags.map(t=>`<span class="state">${esc(t.name||t)}</span>`).join(' ')}</div></div>`:''}</div></div>`;
    $('#backScenes').onclick=()=>{view='scenes';entityMode.scenes='library';renderEntities('scenes')};if($('#playScenePage'))$('#playScenePage').onclick=()=>playMedia(firstMedia.id);if($('#playSceneInfo'))$('#playSceneInfo').onclick=()=>{if(firstMedia)playMedia(firstMedia.id)};if($('#monitorScenePage'))$('#monitorScenePage').onclick=async e=>{e.currentTarget.disabled=true;e.currentTarget.textContent='Starting…';try{await api(localId?`/api/library/scenes/${localId}/monitor`:`/api/metadata/scenes/${encodeURIComponent(id)}/monitor`,post());notify('Monitoring started. ScarletX is searching and downloading in the background.','ok');setTimeout(()=>scenePage(id,localId),800)}catch(err){notify(err.message,'error');e.currentTarget.disabled=false}};
    $$('[data-scene-performer]').forEach(b=>b.onclick=()=>performerProfile(b.dataset.scenePerformer,b.dataset.scenePerformerLocalId||null));$$('[data-scene-studio]').forEach(b=>b.onclick=()=>studioProfile(b.dataset.sceneStudio,b.dataset.sceneStudioLocalId||null));
  }catch(e){if(!navigationGenerationCurrent(generation))return;notify(e.message,'error')}
}

async function remoteDetail(type,id){if(type==='studios')return studioProfile(id,null);try{let x=await api(`/api/metadata/${type}/${encodeURIComponent(id)}`);if(type==='performers')return modal(x.name||'Performer',performerDetailBody(x,id));modal(x.title||x.name||'Details',`<div class="formgrid"><div class="span2"><p>${esc(x.description||x.bio||'No description available.')}</p></div>${x.release_date?`<div><b>Release</b><div class="muted">${fmtDate(x.release_date)}</div></div>`:''}</div>`)}catch(e){notify(e.message,'error')}}
async function localDetail(type,id){try{let x=await api(`/api/library/${type}/${encodeURIComponent(id)}/detail`);if(!x)return;if(type==='performers')return modal(x.name||'Performer',performerDetailBody({...x,id:x.tpdb_id},x.tpdb_id,x.monitored));modal(x.title||x.name,`<div class="formgrid"><div><b>Monitored</b><div class="muted">${x.monitored?'Yes':'No'}</div></div>${type==='scenes'?`<div><b>Studio</b><div class="muted">${esc(x.studio||'—')}</div></div><div class="span2"><b>Files</b><div class="muted">${(x.files||[]).map(f=>esc(f.path)).join('<br>')||'No media files tracked'}</div></div>`:''}</div>`)}catch(e){notify(e.message,'error')}}


// Media-library paging and rendering are owned by ui_overrides.js.

function playerSceneDetails(x){
  let facts=[x.studio&&['Studio',x.studio],x.release_date&&['Released',fmtDate(x.release_date)],x.performers?.length&&['Performers',x.performers.map(p=>esc(p.name)).join(', ')],x.tags?.length&&['Tags',x.tags.map(esc).join(', ')]].filter(Boolean),description=x.description?`<p class="player-scene-description">${esc(x.description)}</p>`:'';
  if(!description&&!facts.length)return '';
  return `<div class="profile-section player-scene-details"><h2>Scene Details</h2>${description}${facts.length?`<div class="profile-facts">${facts.map(([label,value])=>`<div class="profile-fact"><b>${label}</b><span>${value}</span></div>`).join('')}</div>`:''}</div>`;
}

async function playMedia(id){
  const generation=nextNavigationGeneration();
  try{
    let x=await api(`/api/media-files/${encodeURIComponent(id)}/detail`);
    if(!navigationGenerationCurrent(generation))return;$('#app').innerHTML=pageHead(x.scene_title,'',`<button class="btn" id="backLibrary">← Library</button><button class="btn" id="favoritePlayer">${x.favorite?'★ Favorite':'☆ Favorite'}</button><button class="btn" id="makePreview">Generate Preview</button>`)+`<div class="player-shell"><video id="mediaPlayer" controls playsinline preload="metadata" poster="/api/media-files/${id}/screengrab" src="/api/media-files/${id}/stream"></video>${playerSceneDetails(x)}<div class="profile-section"><h2>Media Information</h2><div class="profile-facts"><div class="profile-fact"><b>Resolution</b><span>${x.width&&x.height?`${x.width} × ${x.height}`:x.quality||'—'}</span></div><div class="profile-fact"><b>Duration</b><span>${durationText(x.duration_seconds)}</span></div><div class="profile-fact"><b>Size</b><span>${bytes(x.size_bytes)}</span></div><div class="profile-fact"><b>Video</b><span>${esc(x.video_codec||'—')}</span></div><div class="profile-fact"><b>Container</b><span>${esc(x.container||'—')}</span></div></div></div>`;
    $('#backLibrary').onclick=()=>{view='library';render()};$('#favoritePlayer').onclick=async()=>{x.favorite=!x.favorite;await api(`/api/media-files/${id}/playback`,patch({favorite:x.favorite}));$('#favoritePlayer').textContent=x.favorite?'★ Favorite':'☆ Favorite'};$('#makePreview').onclick=async e=>{e.currentTarget.disabled=true;try{let r=await api(`/api/media-files/${id}/preview`,post());notify(r.status==='ready'?'Preview is already ready.':'Preview generation started.','ok')}catch(err){notify(err.message,'error')}finally{e.currentTarget.disabled=false}};
    let v=$('#mediaPlayer'),lastSave=0,started=false;v.onloadedmetadata=()=>{if(x.position_seconds>5&&x.position_seconds<(v.duration-10))v.currentTime=x.position_seconds};v.onplay=async()=>{if(started)return;started=true;try{await api(`/api/media-files/${id}/playback`,patch({played:true}))}catch(_){}};v.ontimeupdate=()=>{if(Math.abs(v.currentTime-lastSave)<10)return;lastSave=v.currentTime;api(`/api/media-files/${id}/playback`,patch({position_seconds:v.currentTime})).catch(()=>{})};v.onpause=()=>api(`/api/media-files/${id}/playback`,patch({position_seconds:v.currentTime})).catch(()=>{});v.onended=()=>api(`/api/media-files/${id}/playback`,patch({position_seconds:0})).catch(()=>{});
  }catch(e){if(!navigationGenerationCurrent(generation))return;notify(e.message,'error')}
}

const WANTED_PAGE_SIZE=50;
let wantedPage=0,wantedRequest=0;
async function wanted(){
  const requestId=++wantedRequest;
  $('#app').innerHTML=pageHead('Wanted','Monitored scenes that are missing media files.',`<button class="btn primary" id="searchWanted">Search Wanted</button>`)+`<div id="wantedBody" aria-live="polite">Loading…</div>`;
  const body=$('#wantedBody');
  $('#searchWanted').onclick=async()=>{let b=$('#searchWanted');b.disabled=true;b.textContent='Searching…';try{let r=await api('/api/wanted/search?limit=25',post());notify(`Checked ${r.checked}; queued ${r.queued}.`,'ok');if(view==='wanted'&&body.isConnected)wanted()}catch(e){notify(e.message,'error')}finally{b.disabled=false}};
  try{
    const offset=wantedPage*WANTED_PAGE_SIZE;
    const results=await api(`/api/wanted/missing?limit=${WANTED_PAGE_SIZE+1}&offset=${offset}`);
    if(view!=='wanted'||requestId!==wantedRequest||!body.isConnected)return;
    if(!results.length&&wantedPage>0){wantedPage=0;return wanted()}
    const rows=results.slice(0,WANTED_PAGE_SIZE),hasMore=results.length>WANTED_PAGE_SIZE;
    body.innerHTML=rows.length?`<div class="tablewrap"><table class="table"><thead><tr><th>Scene</th><th>Release</th><th>Status</th></tr></thead><tbody>${rows.map(x=>`<tr><td><b>${esc(x.title)}</b></td><td>${fmtDate(x.release_date)}</td><td><span class="state warn">Missing</span></td></tr>`).join('')}</tbody></table></div><div class="pager"><button class="btn small" id="wantedPrevious" ${wantedPage===0?'disabled':''}>Previous</button><span>Page ${wantedPage+1} · Showing ${offset+1}–${offset+rows.length}</span><button class="btn small" id="wantedNext" ${hasMore?'':'disabled'}>Next</button></div>`:empty('Nothing is wanted. All monitored scenes have files.');
    if(rows.length){$('#wantedPrevious').onclick=()=>{wantedPage=Math.max(0,wantedPage-1);wanted()};$('#wantedNext').onclick=()=>{wantedPage++;wanted()}}
  }catch(e){if(view==='wanted'&&requestId===wantedRequest&&body.isConnected){body.textContent='Could not load wanted scenes. Open Wanted to retry.';notify(e.message,'error')}}
}

function activityPager(kind,page,total,pageSize){let pages=Math.max(1,Math.ceil(total/pageSize));if(total<=pageSize)return'';let numbers=Array.from({length:pages},(_,i)=>i+1).filter(n=>pages<=7||n===1||n===pages||Math.abs(n-page)<=1).map(n=>`<button class="btn small" data-activity-page="${kind}" data-page="${n}" ${n===page?'disabled':''}>${n}</button>`).join('');return `<div class="pager activity-pager"><button class="btn small" data-activity-page="${kind}" data-page="${page-1}" ${page<=1?'disabled':''}>Previous</button>${numbers}<button class="btn small" data-activity-page="${kind}" data-page="${page+1}" ${page>=pages?'disabled':''}>Next</button></div>`}
// Download toolbar is owned by download_controls.js.
// Queue rendering is owned by ui_overrides.js and processing_queue_overrides.js.
async function resyncLiveQueue(){
  if(liveQueueBusy)return;
  liveQueueBusy=true;
  try{liveQueueSnapshot=await api('/api/activity/queue');applyLiveQueue(liveQueueSnapshot)}catch(_){}finally{liveQueueBusy=false}
}
function mergeLiveQueueJob(job){
  let rows=[...(liveQueueSnapshot.tracked||[])],key=String(job.external_id||job.id||''),i=rows.findIndex(x=>String(x.external_id||x.id||'')===key);
  if(i>=0)rows[i]={...rows[i],...job};else rows.push(job);
  liveQueueSnapshot={...liveQueueSnapshot,tracked:rows};applyLiveQueue(liveQueueSnapshot);
}
function scheduleLiveQueueFallback(){
  if(liveQueueFallback&&!document.hidden&&!liveQueueTimer)liveQueueTimer=setTimeout(()=>{liveQueueTimer=null;refreshLiveQueueFallback()},15000);
}
async function refreshLiveQueueFallback(){
  if(!liveQueueFallback||document.hidden)return;
  await resyncLiveQueue();
  scheduleLiveQueueFallback();
}
window.addEventListener('scarletx:queue-event',e=>{
  let detail=e.detail||{},kind=detail.kind,payload=detail.payload||{};
  if(kind==='snapshot'){liveQueueSnapshot=payload;applyLiveQueue(liveQueueSnapshot);return}
  if((kind==='progress'||kind==='transition')&&payload.job){mergeLiveQueueJob(payload.job);return}
  if(kind==='resync'){
    if(payload.snapshot){liveQueueSnapshot=payload.snapshot;applyLiveQueue(liveQueueSnapshot)}else resyncLiveQueue();
  }
});
window.addEventListener('scarletx:queue-stream-fallback',()=>{
  liveQueueFallback=true;
  scheduleLiveQueueFallback();
});
window.addEventListener('scarletx:queue-stream-healthy',()=>{liveQueueFallback=false;stopLiveQueue()});
document.addEventListener('visibilitychange',()=>{
  stopLiveQueue();
  if(!document.hidden&&liveQueueFallback)refreshLiveQueueFallback();
});

async function activity(){
  const activityControls=`<label class="download-queue-size" title="Rows shown in the active queue"><span>Show</span><select id="activityQueuePageSize" aria-label="Queue rows per page">${[25,50,100].map(size=>`<option value="${size}" ${ACTIVITY_QUEUE_PAGE_SIZE===size?'selected':''}>${size}</option>`).join('')}</select><span>rows</span></label><button class="btn" id="pauseDownloader">Pause Downloads</button><button class="btn" id="restartDownloader">Restart Downloader</button><button class="btn" id="processNow">Process Completed</button><button class="btn danger" id="clearAllDownloads">Clear All Downloads</button>`;
  $('#app').innerHTML=pageHead('Downloads','Manage active, queued, and completed downloads.',activityControls)+`<section class="download-summary" data-download-summary aria-label="Download summary"><div class="download-summary-item"><strong id="downloadActiveCount">—</strong><span>Active</span></div><div class="download-summary-item"><strong id="downloadQueuedCount">—</strong><span>Waiting</span></div><div class="download-summary-item"><strong id="downloadSpeed">—</strong><span>Current speed</span></div><div class="download-summary-item"><strong id="downloadRemaining">—</strong><span>Remaining</span></div></section><div class="panel download-queue-panel"><div class="panel-head download-queue-panel-head"><div><h2>Queue</h2><span class="download-queue-meta">Sorted by priority · newest first</span></div><span class="client-chip" id="liveQueueState">LIVE</span></div><div id="activityQueue"></div><div class="download-queue-footer"><span><b>Queue speed</b> <span id="downloadQueueSpeed">—</span></span><span><b>Connections</b> <span id="downloadQueueConnections">—</span></span><span><b>Auto-import</b> On</span></div></div><div class="download-secondary-sections"><div class="panel"><div class="panel-head"><h2>Completed</h2></div><div id="activityCompleted"></div></div><div class="panel"><div class="panel-head"><h2>Failed</h2><button class="btn small danger" id="clearFailed">Clear Failed</button></div><div id="activityFailed"></div></div><div class="panel"><div class="panel-head"><h2>History</h2></div><div id="activityHistory"></div></div></div>`;
  $('#processNow').onclick=async()=>{try{let r=await api('/api/downloads/process',post());notify(`Checked ${r.checked}; imported ${r.imported}; failed ${r.failed}.`,'ok');activity()}catch(e){notify(e.message,'error')}};
  $('#pauseDownloader').onclick=toggleAllNativeDownloads;
  $('#clearAllDownloads').onclick=clearAllDownloads;
  $('#restartDownloader').onclick=async e=>{if(!confirm('Restart the built-in downloader? The active transfer will pause briefly and resume from saved partial data.'))return;let b=e.currentTarget;b.disabled=true;b.textContent='Restarting…';try{let r=await api('/api/download-client/restart',post());notify(`Downloader restarted; ${r.requeued||0} job${r.requeued===1?'':'s'} requeued.`,'ok');await resyncLiveQueue()}catch(err){notify(err.message,'error');b.disabled=false;b.textContent='Restart Downloader'}};
  $('#activityQueuePageSize').onchange=async e=>{ACTIVITY_QUEUE_PAGE_SIZE=Number(e.currentTarget.value)||25;activityQueuePage=1;activityQueuePageRows=[];try{await resyncLiveQueue()}catch(err){notify(err.message,'error')}};
  $('#clearFailed').onclick=async e=>{if(!confirm('Clear all failed downloads and their partial files?'))return;e.currentTarget.disabled=true;try{let r=await api('/api/downloads/failed',{method:'DELETE'});notify(`Cleared ${r.cleared} failed download${r.cleared===1?'':'s'}.`,'ok');activity()}catch(err){notify(err.message,'error');e.currentTarget.disabled=false}};
  $('#activityQueue').onclick=async e=>{let pg=e.target.closest('[data-activity-page="queue"]');if(pg&&!pg.disabled){activityQueuePage=Number(pg.dataset.page)||1;applyLiveQueue(liveQueueSnapshot);return}let b=e.target.closest('[data-native-act]');if(!b)return;b.disabled=true;try{await api(`/api/downloads/native/${encodeURIComponent(b.dataset.job)}/${b.dataset.nativeAct}`,post());await resyncLiveQueue()}catch(err){notify(err.message,'error');b.disabled=false}};
  await Promise.all([resyncLiveQueue(),refreshDownloadControl(),initializeActivityLists()]);
}



async function calendar(){
  $('#app').innerHTML=pageHead('Calendar','Upcoming release dates for monitored scenes.')+`<div id="calendarBody"></div>`;try{let rows=await api('/api/calendar');if(view!=='calendar')return;$('#calendarBody').innerHTML=rows.length?`<div class="tablewrap"><table class="table"><thead><tr><th>Date</th><th>Scene</th><th>Monitored</th></tr></thead><tbody>${rows.map(x=>`<tr><td>${fmtDate(x.date)}</td><td><b>${esc(x.title)}</b></td><td><span class="state ${x.monitored?'good':'warn'}">${x.monitored?'Yes':'No'}</span></td></tr>`).join('')}</tbody></table></div>`:empty('No upcoming monitored releases.')}catch(e){notify(e.message,'error')}
}

let settingsTab='general',settingsRequest=0;
async function settings(){
  const request=++settingsRequest;
  let loaded;
  try{loaded=await api('/api/settings')}catch(e){return notify(e.message,'error')}
  if(view!=='settings')return;
  if(request!==settingsRequest)return;
  settingsCache=loaded;
  let tabs=[['general','General'],['metadata','TPDB'],['indexers','Indexers'],['downloads','Download Client'],['media','Media Management'],['automation','Automation'],['backups','Backups'],['security','Security'],['system','System']];
  $('#app').innerHTML=pageHead('Settings','Configure ScarletX and its integrations.')+`<div class="settings-layout"><div class="settings-nav">${settingsNavigation(tabs)}</div><div id="settingsBody"></div></div>`;
  $$('.settings-nav button').forEach(b=>b.onclick=()=>{settingsTab=b.dataset.tab;settings()});
  const body=$('#settingsBody'),tab=settingsTab;
  try{await renderSettingsTab();if(request===settingsRequest&&view==='settings'&&body.isConnected)enhanceSettings(tab,body)}catch(error){if(body.isConnected)notify(error.message,'error')}
}
function val(id){return $(id).value.trim()}
async function renderSettingsTab(){let s=settingsCache,el=$('#settingsBody');
 if(settingsTab==='general'){el.innerHTML=`<div class="settings-panel"><h2>General</h2><p>ScarletX application identity and logging.</p><div class="formgrid"><div class="field"><label>Application name</label><input class="input" id="appName" value="${esc(s.general.app_name)}"></div><div class="field"><label>Log level</label><select id="logLevel">${['DEBUG','INFO','WARNING','ERROR'].map(x=>`<option ${s.general.log_level===x?'selected':''}>${x}</option>`).join('')}</select></div></div><div class="divider"></div><button class="btn primary" id="saveGeneral">Save</button></div>`;$('#saveGeneral').onclick=()=>saveSetting('/api/settings/general',{app_name:val('#appName'),log_level:val('#logLevel')});return}
 if(settingsTab==='metadata'){el.innerHTML=`<div class="settings-panel"><h2>ThePornDB</h2><p>Primary metadata source for scenes, performers, and studios.</p><div class="formgrid"><div class="field span2"><label>API key</label><input class="input" id="tpdbKey" type="password" aria-describedby="tpdbKeyHelp" placeholder="${s.theporndb.configured?'Configured — leave blank to keep current':'Enter TPDB API key'}"><span class="hint" id="tpdbKeyHelp">Need a key? <a href="https://theporndb.net/register" target="_blank" rel="noopener noreferrer">Create a TPDB account</a> or sign in, then open <a href="https://theporndb.net/user/api-tokens" target="_blank" rel="noopener noreferrer">API Tokens</a> and generate a token. Copy it into this field and select Save changes. Leave this field blank to keep your existing key.</span></div><div class="field span2"><label>API URL</label><input class="input" id="tpdbUrl" value="${esc(s.theporndb.base_url)}"></div></div><div class="divider"></div><button class="btn primary" id="saveTPDB">Save TPDB</button></div>`;$('#saveTPDB').onclick=()=>saveSetting('/api/settings/theporndb',{api_key:val('#tpdbKey')||null,base_url:val('#tpdbUrl')});return}
 if(settingsTab==='indexers')return renderIndexers();
 if(settingsTab==='downloads')return renderDownloadSettings();
 if(settingsTab==='media')return renderMediaSettings();
 if(settingsTab==='automation'){let a=s.automation,r=s.rss;el.innerHTML=`<div class="settings-panel"><h2>Automation</h2><p>Automatic scene searches and RSS matching.</p><div class="formgrid"><div class="field"><label>Automatic search</label><select id="autoEnabled"><option value="true" ${a.enabled?'selected':''}>Enabled</option><option value="false" ${!a.enabled?'selected':''}>Disabled</option></select></div><div class="field"><label>Interval minutes</label><input class="input" id="autoInterval" type="number" min="5" value="${a.interval_minutes}"></div><div class="field"><label>Batch size</label><input class="input" id="autoBatch" type="number" min="1" value="${a.batch_size}"></div></div><div class="divider"></div><h2>RSS</h2><div class="formgrid"><div class="field"><label>RSS sync</label><select id="rssEnabled"><option value="true" ${r.enabled?'selected':''}>Enabled</option><option value="false" ${!r.enabled?'selected':''}>Disabled</option></select></div><div class="field"><label>Interval minutes</label><input class="input" id="rssInterval" type="number" min="5" value="${r.interval_minutes}"></div><div class="field"><label>Releases per indexer</label><input class="input" id="rssMax" type="number" min="10" value="${r.max_releases_per_indexer}"></div><div class="field"><label>Max grabs per cycle</label><input class="input" id="rssGrab" type="number" min="1" value="${r.max_grabs_per_cycle}"></div></div><div class="divider"></div><button class="btn primary" id="saveAuto">Save Automation</button></div>`;$('#saveAuto').onclick=async()=>{const automation={enabled:val('#autoEnabled')==='true',interval_minutes:Number(val('#autoInterval')),batch_size:Number(val('#autoBatch'))},rss={enabled:val('#rssEnabled')==='true',interval_minutes:Number(val('#rssInterval')),max_releases_per_indexer:Number(val('#rssMax')),max_grabs_per_cycle:Number(val('#rssGrab'))};await api('/api/settings/automation',patch(automation));await api('/api/settings/rss',patch(rss));notify('Automation settings saved.','ok');settings()};return}
 if(settingsTab==='backups'){let b=s.backups;el.innerHTML=`<div class="settings-panel"><h2>Backups</h2><p>Local SQLite database backup rotation.</p><div class="formgrid"><div class="field"><label>Enabled</label><select id="backupEnabled"><option value="true" ${b.enabled?'selected':''}>Enabled</option><option value="false" ${!b.enabled?'selected':''}>Disabled</option></select></div><div class="field"><label>Directory</label><input class="input" id="backupDir" value="${esc(b.directory)}"></div><div class="field"><label>Interval hours</label><input class="input" id="backupHours" type="number" value="${b.interval_hours}"></div><div class="field"><label>Keep</label><input class="input" id="backupKeep" type="number" value="${b.keep}"></div></div><div class="divider"></div><div class="actions"><button class="btn primary" id="saveBackup">Save</button><button class="btn" id="backupNow">Backup Now</button></div></div>`;$('#saveBackup').onclick=()=>saveSetting('/api/settings/backups',{enabled:val('#backupEnabled')==='true',directory:val('#backupDir'),interval_hours:Number(val('#backupHours')),keep:Number(val('#backupKeep'))});$('#backupNow').onclick=async()=>{try{let r=await api('/api/backups',post());notify(`Backup created: ${r.path}`,'ok')}catch(e){notify(e.message,'error')}};return}
 if(settingsTab==='security'){let z=s.security;el.innerHTML=`<div class="settings-panel"><h2>UI Authentication</h2><p>Administrator sign-in is required. Use this form to update your credentials.</p><div class="formgrid"><div class="field"><label>UI authentication</label><select id="uiAuthEnabled" disabled><option value="true" selected>Required</option></select></div><div class="field"><label>Administrator username</label><input class="input" id="securityUsername" autocomplete="username" value="${esc(window.scarletxUsername||'')}"></div><div class="field"><label>Password</label><input class="input" id="securityPassword" type="password" minlength="12" autocomplete="new-password"></div><div class="field"><label>Confirm password</label><input class="input" id="securityPasswordConfirm" type="password" minlength="12" autocomplete="new-password"></div></div><div class="divider"></div><h2>API Security</h2><p>Integrations authenticate with your ScarletX API key. Keep this key private.</p><div class="formgrid"><div class="field"><label>API key</label><select id="apiEnabled" disabled><option value="true" selected>Required</option></select></div><div class="field"><label>API key value</label><input class="input" id="apiKey" type="password" placeholder="${z.api_key_configured?'Configured — blank keeps current':'Enter a key'}"></div></div><div class="divider"></div><button class="btn primary" id="saveSecurity">Save Security</button></div>`;$('#saveSecurity').onclick=async()=>{let enabled=val('#uiAuthEnabled')==='true',password=$('#securityPassword').value,passwordConfirm=$('#securityPasswordConfirm').value;if(enabled&&(password.length<12||password!==passwordConfirm))return notify(password.length<12?'Password must be at least 12 characters.':'Passwords do not match.','error');try{await api('/api/settings/security',patch({ui_auth_enabled:enabled,username:enabled?val('#securityUsername'):null,password:enabled?password:null,password_confirm:enabled?passwordConfirm:null,api_key_enabled:val('#apiEnabled')==='true',api_key:val('#apiKey')||null}));notify(`UI authentication ${enabled?'enabled':'disabled'}.`,'ok');location.reload()}catch(e){notify(e.message,'error')}};return}
 if(settingsTab==='system')return renderSystemSettings();
}
async function renderSystemSettings(){let el=$('#settingsBody');el.innerHTML=`<div class="settings-panel"><h2>System</h2><p>Runtime health and storage.</p><div id="systemSettings">Loading…</div></div>`;let [st,h,d]=await Promise.all([api('/api/system/status'),api('/api/system/health'),api('/api/system/diskspace')]);if(!el.isConnected||view!=='settings'||settingsTab!=='system')return;el.querySelector('#systemSettings').innerHTML=`<div class="formgrid"><div><b>Version</b><div class="muted">${esc(st.version)}</div></div><div><b>Database</b><div class="muted">${esc(st.database)}</div></div><div><b>Health</b><div class="state ${h.status==='ok'?'good':h.status==='warning'?'warn':'bad'}">${esc(h.status)}</div></div><div><b>Tracked media files</b><div class="muted">${st.media_files}</div></div></div><div class="divider"></div>${d.length?`<div class="tablewrap"><table class="table"><thead><tr><th>Scene Root</th><th>Path</th><th>Free</th></tr></thead><tbody>${d.map(x=>`<tr><td>${esc(x.name)}</td><td>${esc(x.path)}</td><td>${x.exists?bytes(x.free_bytes):'Missing'}</td></tr>`).join('')}</tbody></table></div>`:empty('No scene root folder configured.')}
<section class="system-reset-panel" id="systemStartOverPanel"><h3>Start Over</h3><p>Use this only when you want to clear the ScarletX library and begin again.</p><ul><li>Deletes tracked media files in configured scene roots and generated playback assets.</li><li>Removes all scenes, performers, studios, tags, and library associations.</li><li>This operation preserves all settings, root folders, quality profiles, NNTP/download settings, indexer settings, download staging, backups, and history.</li></ul><p class="hint">This does not touch NNTP or indexer information. The reset permanently removes the library content listed above.</p><div class="actions"><button class="btn danger" id="startOver">Start Over</button><button class="btn danger" id="confirmStartOver" hidden>Confirm Start Over</button><button class="btn" id="cancelStartOver" hidden>Cancel</button></div><p class="system-reset-confirm" id="startOverPrompt" hidden>Click “Confirm Start Over” to permanently delete the library content described above.</p></section>`;const start=$('#startOver'),confirmButton=$('#confirmStartOver'),cancel=$('#cancelStartOver'),prompt=$('#startOverPrompt');start.onclick=()=>{start.hidden=true;confirmButton.hidden=false;cancel.hidden=false;prompt.hidden=false};cancel.onclick=()=>{start.hidden=false;confirmButton.hidden=true;cancel.hidden=true;prompt.hidden=true};confirmButton.onclick=async()=>{confirmButton.disabled=true;cancel.disabled=true;confirmButton.textContent='Resetting…';try{let result=await api('/api/system/start-over',post());notify(`Start Over complete: removed ${result.media_files} media file${result.media_files===1?'':'s'}, ${result.performers} performers, and ${result.studios} studios.`,'ok');await settings()}catch(error){notify(error.message,'error');confirmButton.disabled=false;cancel.disabled=false;confirmButton.textContent='Confirm Start Over'}}}
async function saveSetting(path,body){try{await api(path,patch(body));notify('Settings saved.','ok');settings()}catch(e){notify(e.message,'error')}}
async function renderIndexers(){let el=$('#settingsBody'),rows=settingsCache.newznab_indexers;el.innerHTML=`<div class="settings-panel"><h2>Newznab Indexers</h2><p>Usenet indexers used for adult scene search and RSS.</p><div id="indexers">${rows.map(indexerRow).join('')}</div><div class="actions"><button class="btn" id="addIndexer">＋ Add Indexer</button><button class="btn primary" id="saveIndexers">Save Indexers</button></div></div>`;$('#addIndexer').onclick=()=>$('#indexers').insertAdjacentHTML('beforeend',indexerRow({}));$('#indexers').onclick=e=>{let b=e.target.closest('[data-remove-indexer]');if(b)b.closest('.indexer').remove()};$('#saveIndexers').onclick=async()=>{let indexers=$$('.indexer').map(r=>({name:r.querySelector('[data-k=name]').value.trim(),url:r.querySelector('[data-k=url]').value.trim(),api_key:r.querySelector('[data-k=key]').value.trim()||null,adult_categories:r.querySelector('[data-k=cats]').value.split(',').map(x=>Number(x.trim())).filter(Boolean),enabled:r.querySelector('[data-k=enabled]').value==='true',rss_enabled:r.querySelector('[data-k=rss]').value==='true',priority:Number(r.querySelector('[data-k=priority]').value||25)})).filter(x=>x.name&&x.url);try{await api('/api/settings/newznab',patch({indexers}));notify('Indexers saved.','ok');settings()}catch(e){notify(e.message,'error')}}}
function indexerRow(x={}){return `<div class="indexer"><div class="indexer-grid"><div class="field"><label>Name</label><input class="input" data-k="name" value="${esc(x.name||'')}"></div><div class="field"><label>API URL</label><input class="input" data-k="url" value="${esc(x.url||'')}"></div><div class="field"><label>API key</label><input class="input" type="password" data-k="key" placeholder="${x.api_key_configured?'Configured — blank keeps current':''}"></div><div class="field"><label>Priority</label><input class="input" type="number" data-k="priority" value="${x.priority||25}"></div><div class="field"><label>Adult categories</label><input class="input" data-k="cats" value="${esc((x.adult_categories||[6000,6010,6020,6040]).join(','))}"></div><div class="field"><label>Enabled</label><select data-k="enabled"><option value="true" ${x.enabled!==false?'selected':''}>Yes</option><option value="false" ${x.enabled===false?'selected':''}>No</option></select></div><div class="field"><label>RSS</label><select data-k="rss"><option value="true" ${x.rss_enabled!==false?'selected':''}>Yes</option><option value="false" ${x.rss_enabled===false?'selected':''}>No</option></select></div><div class="field"><label>&nbsp;</label><button class="btn danger" data-remove-indexer>Remove</button></div></div></div>`}
function providerRow(x={}){return `<div class="provider" data-provider><div class="provider-grid"><div class="field"><label>Name</label><input class="input" data-p="name" value="${esc(x.name||'')}"></div><div class="field"><label>NNTP Host</label><input class="input" data-p="host" value="${esc(x.host||'')}"></div><div class="field"><label>Port</label><input class="input" type="number" data-p="port" value="${x.port||563}"></div><div class="field"><label>Username</label><input class="input" data-p="username" value="${esc(x.username||'')}"></div><div class="field"><label>Password</label><input class="input" type="password" data-p="password" placeholder="${x.password_configured?'Configured — blank keeps current':''}"></div><div class="field"><label>SSL/TLS</label><input class="input" value="Required" disabled><span class="hint">Plaintext NNTP is not supported.</span></div><div class="field"><label>Connections</label><input class="input" type="number" min="1" max="200" data-p="connections" value="${x.connections||8}"></div></div><div class="actions" style="margin-top:8px"><div class="field" style="width:105px"><label>Priority</label><input class="input" type="number" min="1" max="50" data-p="priority" value="${x.priority||25}"></div><div class="field" style="width:105px"><label>Enabled</label><select data-p="enabled"><option value="true" ${x.enabled!==false?'selected':''}>Yes</option><option value="false" ${x.enabled===false?'selected':''}>No</option></select></div><button class="btn small" data-test-provider>Test</button><button class="btn small danger" data-remove-provider>Remove</button></div></div>`}
function collectProviders(){return $$('[data-provider]').map(r=>({name:r.querySelector('[data-p=name]').value.trim(),host:r.querySelector('[data-p=host]').value.trim(),port:Number(r.querySelector('[data-p=port]').value||563),username:r.querySelector('[data-p=username]').value.trim(),password:r.querySelector('[data-p=password]').value.trim()||null,use_ssl:true,connections:Number(r.querySelector('[data-p=connections]').value||8),enabled:r.querySelector('[data-p=enabled]').value==='true',priority:Number(r.querySelector('[data-p=priority]').value||25)})).filter(x=>x.name&&x.host)}
async function renderDownloadSettings(){let el=$('#settingsBody'),n=settingsCache.native_usenet,tools=n.tools||{};el.innerHTML=`<div class="settings-panel"><h2>ScarletX Built-In Usenet</h2><p>ScarletX downloads NZBs directly over encrypted NNTP/TLS. Plaintext NNTP is disabled.</p><div class="formgrid"><div class="field"><label>Built-in downloader</label><select id="nativeEnabled"><option value="true" ${n.enabled?'selected':''}>Enabled</option><option value="false" ${!n.enabled?'selected':''}>Disabled</option></select></div><div class="field"><label>Adaptive connection cap</label><input class="input" id="nativeConnections" type="number" min="1" max="200" value="${n.max_connections}"><span class="hint">ScarletX starts smaller and automatically ramps toward this cap while measured throughput keeps improving. Provider values remain hard maximums.</span></div><div class="field span2"><label>Incomplete directory</label><input class="input" id="nativeIncomplete" value="${esc(n.incomplete_dir)}"></div><div class="field span2"><label>Completed directory</label><input class="input" id="nativeComplete" value="${esc(n.complete_dir)}"></div><div class="field"><label>Extra transient retries</label><input class="input" id="nativeRetries" type="number" min="0" max="3" value="${Math.min(3,n.max_retries)}"><span class="hint">Total extra attempts across all providers. Missing articles immediately rotate servers.</span></div><div class="field"><div class="speed-limit-control"><div class="speed-limit-head"><label>Download speed limit</label><output class="speed-limit-value" id="nativeSpeedValue">${Number(n.speed_limit_mb_s||0)>0?`${Number(n.speed_limit_mb_s).toFixed(Number(n.speed_limit_mb_s)%1?1:0)} MB/s`:'Unlimited'}</output></div><input class="speed-slider" id="nativeSpeed" type="range" min="0" max="250" step="0.5" value="${Math.min(250,Number(n.speed_limit_mb_s||0))}" aria-label="Download speed limit in megabytes per second"><div class="speed-scale"><span>Unlimited</span><span>50</span><span>100</span><span>150</span><span>200</span><span>250 MB/s</span></div><span class="hint">Applies to ScarletX's built-in downloader. Move fully left for no speed limit.</span></div></div><div class="field"><label>PAR2 repair</label><select id="nativeRepair"><option value="true" ${n.repair_enabled?'selected':''}>Enabled</option><option value="false" ${!n.repair_enabled?'selected':''}>Disabled</option></select></div><div class="field"><label>Unpack archives</label><select id="nativeUnpack"><option value="true" ${n.unpack_enabled?'selected':''}>Enabled</option><option value="false" ${!n.unpack_enabled?'selected':''}>Disabled</option></select></div></div><div class="divider"></div><h2>Usenet Providers</h2><p>Astraweb and Newshosting are preconfigured for this private development build. ScarletX uses TLS-only, keeps provider sessions warm, and dynamically stripes scene segments across the fastest healthy servers.</p><div id="providers">${(n.providers||[]).map(providerRow).join('')}</div><div class="actions"><button class="btn" id="addProvider">＋ Add Provider</button><button class="btn primary" id="saveNative">Save Download Settings</button></div><div class="divider"></div><h2>Post-processing tools</h2><div class="tool-grid"><span class="tool-pill ${tools.sabctools?'good':'warn'}">SIMD yEnc ${tools.sabctools?'Ready':'Fallback'}</span><span class="tool-pill ${tools.par2?'good':'warn'}">PAR2 ${tools.par2?'Ready':'Not installed'}</span><span class="tool-pill ${tools.unrar?'good':'warn'}">unrar ${tools.unrar?'Ready':'Not installed'}</span><span class="tool-pill ${tools['7z']?'good':'warn'}">7z ${tools['7z']?'Ready':'Not installed'}</span></div><p class="hint">Direct video NZBs work without these tools. RAR/PAR posts need PAR2 plus unrar or 7z for automatic repair and extraction.</p></div>`;
 const speedSlider=$('#nativeSpeed'),speedValue=$('#nativeSpeedValue');
 const updateSpeedLabel=()=>{let v=Number(speedSlider.value||0);speedValue.textContent=v>0?`${v.toFixed(v%1?1:0)} MB/s`:'Unlimited'};
 speedSlider.oninput=updateSpeedLabel;updateSpeedLabel();
 $('#addProvider').onclick=()=>$('#providers').insertAdjacentHTML('beforeend',providerRow({name:'Provider',port:563,use_ssl:true,connections:8,enabled:true,priority:25}));
 $('#providers').onclick=async e=>{let rem=e.target.closest('[data-remove-provider]');if(rem){rem.closest('[data-provider]').remove();return}let test=e.target.closest('[data-test-provider]');if(!test)return;let r=test.closest('[data-provider]'),body={name:r.querySelector('[data-p=name]').value.trim(),host:r.querySelector('[data-p=host]').value.trim(),port:Number(r.querySelector('[data-p=port]').value||563),username:r.querySelector('[data-p=username]').value.trim(),password:r.querySelector('[data-p=password]').value.trim()||null,use_ssl:true,connections:Number(r.querySelector('[data-p=connections]').value||8),enabled:r.querySelector('[data-p=enabled]').value==='true',priority:Number(r.querySelector('[data-p=priority]').value||25)};test.disabled=true;try{let out=await api('/api/download-clients/native/test',post(body));notify(`Connected to ${out.provider} in ${out.latency_ms} ms.`,'ok')}catch(err){notify(err.message,'error')}finally{test.disabled=false}};
 $('#saveNative').onclick=async()=>{try{await api('/api/settings/native-usenet',patch({enabled:val('#nativeEnabled')==='true',providers:collectProviders(),incomplete_dir:val('#nativeIncomplete'),complete_dir:val('#nativeComplete'),max_connections:Number(val('#nativeConnections')),max_retries:Number(val('#nativeRetries')),speed_limit_mb_s:Number(val('#nativeSpeed')),repair_enabled:val('#nativeRepair')==='true',unpack_enabled:val('#nativeUnpack')==='true'}));notify('Built-in Usenet settings saved.','ok');settings()}catch(e){notify(e.message,'error')}};
}
async function renderMediaSettings(){let el=$('#settingsBody'),s=settingsCache.file_management,roots=await api('/api/root-folders'),root=roots.find(x=>x.is_default)||roots[0];if(!el.isConnected||view!=='settings'||settingsTab!=='media')return;el.innerHTML=`<div class="settings-panel"><h2>Media Management</h2><p>Scene root folder and file organization.</p><div class="formgrid"><div class="field"><label>File management</label><select id="fileEnabled"><option value="true" ${s.enabled?'selected':''}>Enabled</option><option value="false" ${!s.enabled?'selected':''}>Disabled</option></select></div><div class="field"><label>Import mode</label><select id="importMode">${['move','copy','hardlink'].map(x=>`<option ${s.import_mode===x?'selected':''}>${x}</option>`).join('')}</select></div><div class="field span2"><label>Scene root folder</label><input class="input" id="sceneRoot" value="${esc(root?.path||'')}"><span class="hint">Use an absolute path accessible to ScarletX.</span></div><div class="field span2"><label>Naming template</label><input class="input" id="sceneTemplate" value="${esc(s.scene_naming_template)}"></div><div class="field"><label>Recycle bin</label><input class="input" id="recycleBin" value="${esc(s.recycle_bin_path||'')}"></div><div class="field"><label>Minimum free space (GB)</label><input class="input" id="minFree" type="number" value="${s.minimum_free_space_gb}"></div></div><div class="divider"></div><button class="btn primary" id="saveMedia">Save Media Management</button></div>`;$('#saveMedia').onclick=async()=>{const basic={enabled:val('#fileEnabled')==='true',scene_naming_template:val('#sceneTemplate')},advanced={import_mode:val('#importMode'),recycle_bin_path:val('#recycleBin'),minimum_free_space_gb:Number(val('#minFree'))},path=val('#sceneRoot');try{await api('/api/settings/file-management',patch(basic));await api('/api/settings/file-management/advanced',patch(advanced));if(path){let body={name:'Scenes',content_type:'scene',path,is_default:true,create_missing:true};if(root)await api(`/api/root-folders/${root.id}`,put(body));else await api('/api/root-folders',post(body))}notify('Media management saved.','ok');settings()}catch(e){notify(e.message,'error')}}}
boot();
