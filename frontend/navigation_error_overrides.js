let navigationGeneration=0;
function nextNavigationGeneration(){navigationGeneration+=1;return navigationGeneration}
function navigationGenerationCurrent(generation){return generation===navigationGeneration}

// Page/detail navigation and entity list/search requests are different race domains.
// Sharing one generation counter caused a legitimate nested render to invalidate the
// request that was supposed to paint the new page. Keep the global generation for
// page/detail transitions and a per-entity request sequence for list/search work.
const entityRequestGeneration={scenes:0,performers:0,studios:0};
function nextEntityRequest(type){
  entityRequestGeneration[type]=(entityRequestGeneration[type]||0)+1;
  return entityRequestGeneration[type];
}
function entityRequestCurrent(type,generation){
  return (entityRequestGeneration[type]||0)===generation;
}

const navigationBaseRender=render;
render=async function(...args){
  nextNavigationGeneration();
  return navigationBaseRender(...args);
};

const navigationBaseRenderEntities=renderEntities;
renderEntities=async function(...args){
  nextNavigationGeneration();
  return navigationBaseRenderEntities(...args);
};

loadEntityLibrary=async function(type,cursor=null,append=false,q=null){
  const generation=nextEntityRequest(type);
  const grid=$('#entityGrid');
  try{
    if(q===null)q=entityLibraryQuery[type]||'';
    if(!append)entityLibraryQuery[type]=q;
    let url=entityPageUrl(type,cursor,q),pending=entityPrefetch.get(url),data=pending?await pending:await api(url);
    entityPrefetch.delete(url);
    if(view!==type||!entityRequestCurrent(type,generation)||$('#entityGrid')!==grid)return;
    paintEntityLibrary(type,data,append);
    if(data.has_more&&data.next_cursor)prefetchEntityPage(type,data.next_cursor,q);
  }catch(e){
    if(view!==type||!entityRequestCurrent(type,generation)||$('#entityGrid')!==grid)return;
    notify(e.message,'error')
  }
};

searchEntity=async function(type,q){
  const generation=nextEntityRequest(type);
  const grid=$('#entityGrid');
  if(!grid)return;
  grid.innerHTML=empty('Searching TPDB…');
  try{
    let d=await api(`/api/search/${type}?q=${encodeURIComponent(q)}`);
    if(view!==type||!entityRequestCurrent(type,generation)||$('#entityGrid')!==grid)return;
    let rows=d.items||d;
    if(type==='scenes'){
      grid.innerHTML=sceneTable(rows,false);
      bindSceneTableActions(grid,false);
      return
    }
    grid.innerHTML=rows.length?rows.map(x=>entityCard(type,x,false)).join(''):empty('No TPDB results found.');
    bindEntityActions(type,false)
  }catch(e){
    if(view!==type||!entityRequestCurrent(type,generation)||$('#entityGrid')!==grid)return;
    grid.innerHTML=empty(e.message)
  }
};

// Profile scene pagination must belong to the navigation that started it. Without
// this check, leaving a performer/studio profile can leave hundreds of sequential
// page requests running in the background and eventually starve fresh UI requests.
loadAllPerformerScenes=async function(id,localId=null,generation=navigationGeneration){
  let items=[],page=1,total=0;
  while(page<=1000){
    if(!navigationGenerationCurrent(generation))return {items,total:items.length,cancelled:true};
    let url=localId?`/api/library/performers/${encodeURIComponent(localId)}/scenes?page=${page}&per_page=100`:`/api/metadata/performers/${encodeURIComponent(id)}/scenes?page=${page}&per_page=100`;
    let result=await api(url);
    if(!navigationGenerationCurrent(generation))return {items,total:items.length,cancelled:true};
    let rows=result.items||[];items.push(...rows);total=Number(result.total||items.length);
    if(page*Number(result.per_page||100)>=total)break;
    page++
  }
  return {items,total:items.length,cancelled:false};
};

loadAllStudioScenes=async function(id,localId=null,generation=navigationGeneration){
  let items=[],page=1,total=0;
  while(page<=1000){
    if(!navigationGenerationCurrent(generation))return {items,total:items.length,cancelled:true};
    let url=localId?`/api/library/studios/${encodeURIComponent(localId)}/scenes?page=${page}&per_page=100`:`/api/metadata/studios/${encodeURIComponent(id)}/scenes?page=${page}&per_page=100`;
    let result=await api(url);
    if(!navigationGenerationCurrent(generation))return {items,total:items.length,cancelled:true};
    let rows=result.items||[];items.push(...rows);total=Number(result.total||items.length);
    if(page*Number(result.per_page||100)>=total)break;
    page++
  }
  return {items,total:items.length,cancelled:false};
};

performerProfile=async function(id,localId=null){
  const generation=nextNavigationGeneration();
  $('#app').innerHTML=pageHead('Performer','Loading performer profile…',`<button class="btn" id="backPerformers">← Performers</button>`)+`<div class="empty">Loading performer information…</div>`;
  $('#backPerformers').onclick=()=>{view='performers';renderEntities('performers')};
  try{
    let local=null;
    if(localId){try{local=await api(`/api/library/performers/${encodeURIComponent(localId)}/detail`)}catch(_){}}
    else{let cached=entityLibraryCache.performers?.items||[],summary=cached.find(v=>String(v.tpdb_id)===String(id))||null;if(summary?.id){try{local=await api(`/api/library/performers/${encodeURIComponent(summary.id)}/detail`)}catch(_){local=summary}}}
    if(!navigationGenerationCurrent(generation))return;
    let resolvedLocalId=localId||local?.id||null;
    let x=local?localPerformerProfile(local):await api(`/api/metadata/performers/${encodeURIComponent(id)}`);
    if(!navigationGenerationCurrent(generation))return;
    let scenes={items:[]};try{scenes=await loadAllPerformerScenes(id,resolvedLocalId,generation)}catch(_){}
    if(!navigationGenerationCurrent(generation))return;
    let img=x.image_url?`/api/artwork/performers/${encodeURIComponent(id)}`:'';let links=Object.entries(x.links||{}).filter(([,v])=>v).map(([k,v])=>`<a class="btn small" target="_blank" rel="noopener" href="${esc(v)}">${esc(k)}</a>`).join('');
    $('#app').innerHTML=pageHead(x.name||'Performer','Cached performer profile',`<button class="btn" id="backPerformers">← Performers</button>${local?.monitored?'':`<button class="btn primary" id="monitorAllPerformer">Monitor All</button>`}`)+`<div class="profile-shell"><div class="profile-image">${img?`<img src="${esc(img)}" alt="${esc(x.name||'Performer')}" loading="eager" onerror="this.remove()">`:'No performer image available.'}</div><div><div class="profile-facts">${performerFacts(x,local?local.monitored:null)}</div>${x.bio?`<div class="profile-section"><h2>Biography</h2><div class="profile-bio">${esc(x.bio)}</div></div>`:''}${links?`<div class="profile-section"><h2>Links</h2><div class="profile-links">${links}</div></div>`:''}</div></div><div class="profile-section"><h2>Studio Scenes</h2><div id="performerSceneList">${sceneProfileList(scenes.items||[])}</div></div>`;
    $('#backPerformers').onclick=()=>{view='performers';renderEntities('performers')};if($('#monitorAllPerformer'))$('#monitorAllPerformer').onclick=async e=>{try{await monitorAllEntity('performers',id,resolvedLocalId,e.currentTarget)}catch(err){notify(err.message,'error')}};bindProfileSceneLinks($('#performerSceneList'));
  }catch(e){if(!navigationGenerationCurrent(generation))return;notify(e.message,'error');if(!navigationGenerationCurrent(generation))return;$('#app').innerHTML=pageHead('Performer','Unable to load performer profile.',`<button class="btn" id="backPerformers">← Performers</button>`)+empty(e.message);$('#backPerformers').onclick=()=>{view='performers';renderEntities('performers')}}
};

studioProfile=async function(id,localId=null){
  const generation=nextNavigationGeneration();
  $('#app').innerHTML=pageHead('Studio','Loading studio…',`<button class="btn" id="backStudios">← Studios</button>`)+empty('Loading studio information…');
  $('#backStudios').onclick=()=>{view='studios';renderEntities('studios')};
  try{
    let local=null;
    if(localId){try{local=await api(`/api/library/studios/${encodeURIComponent(localId)}/detail`)}catch(_){}}
    else{let cached=entityLibraryCache.studios?.items||[],summary=cached.find(v=>String(v.tpdb_id)===String(id))||null;if(summary?.id){try{local=await api(`/api/library/studios/${encodeURIComponent(summary.id)}/detail`)}catch(_){local=summary}}}
    if(!navigationGenerationCurrent(generation))return;
    let resolvedLocalId=localId||local?.id||null;
    let x=local?{...local,id:local.tpdb_id}:await api(`/api/metadata/studios/${encodeURIComponent(id)}`);
    if(!navigationGenerationCurrent(generation))return;
    let scenes={items:[]};try{scenes=await loadAllStudioScenes(id,resolvedLocalId,generation)}catch(_){}
    if(!navigationGenerationCurrent(generation))return;
    let img=(x.poster_url||x.logo_url||x.image_url)?`/api/artwork/studios/${encodeURIComponent(id)}`:'';
    $('#app').innerHTML=pageHead(x.name||'Studio','Cached studio profile',`<button class="btn" id="backStudios">← Studios</button>${local?.monitored?'':`<button class="btn primary" id="monitorAllStudio">Monitor All</button>`}`)+`<div class="profile-shell"><div class="profile-image">${img?`<img src="${esc(img)}" alt="${esc(x.name||'Studio')}" loading="eager" onerror="this.remove()">`:'No studio image available.'}</div><div><div class="profile-facts"><div class="profile-fact"><b>Monitored</b><span>${local?.monitored?'Yes':'No'}</span></div>${x.url?`<div class="profile-fact"><b>Website</b><span><a target="_blank" rel="noopener" href="${esc(x.url)}">Open site</a></span></div>`:''}</div>${x.description?`<div class="profile-section"><h2>About</h2><div class="profile-bio">${esc(x.description)}</div></div>`:''}</div></div><div class="profile-section"><h2>Studio Scenes</h2><div id="studioSceneList">${sceneProfileList(scenes.items||[])}</div></div>`;
    $('#backStudios').onclick=()=>{view='studios';renderEntities('studios')};if($('#monitorAllStudio'))$('#monitorAllStudio').onclick=async e=>{try{await monitorAllEntity('studios',id,resolvedLocalId,e.currentTarget)}catch(err){notify(err.message,'error')}};bindProfileSceneLinks($('#studioSceneList'));
  }catch(e){if(!navigationGenerationCurrent(generation))return;notify(e.message,'error');if(!navigationGenerationCurrent(generation))return;$('#app').innerHTML=pageHead('Studio','Unable to load studio.',`<button class="btn" id="backStudios">← Studios</button>`)+empty(e.message);$('#backStudios').onclick=()=>{view='studios';renderEntities('studios')}}
};
