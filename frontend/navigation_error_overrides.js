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
  const requestedPage=entityPage[type];
  const grid=$('#entityGrid');
  try{
    if(q===null)q=entityLibraryQuery[type]||'';
    if(!append)entityLibraryQuery[type]=q;
    let url=entityPageUrl(type,cursor,q),pending=entityPrefetch.get(url),data=pending?await pending:await api(url);
    entityPrefetch.delete(url);
    if(view!==type||!entityRequestCurrent(type,generation)||$('#entityGrid')!==grid)return;
    entityPageCursors[type][requestedPage]=data.next_cursor||null;
    paintEntityLibrary(type,data,append);
    if(data.has_more&&data.next_cursor)prefetchEntityPage(type,data.next_cursor,q);
    return true
  }catch(e){
    if(view!==type||!entityRequestCurrent(type,generation)||$('#entityGrid')!==grid)return;
    notify(e.message,'error');return false
  }
};

// Entity search has one owner: entity_search.js.

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

async function initProfileSceneCatalog(type,id,localId,generation){
  const list=$(`#${type==='performers'?'performer':'studio'}SceneList`);
  if(!list||!navigationGenerationCurrent(generation))return;
  list.innerHTML=empty('Loading saved scenes…');
  list.insertAdjacentHTML('beforebegin','<div class="profile-catalog-toolbar"><span id="profileCatalogStatus" role="status" aria-live="polite">Loading local library…</span><button class="btn small" id="refreshProfileScenes">Refresh scenes</button></div>');
  const button=$('#refreshProfileScenes'),status=$('#profileCatalogStatus');
  const current=()=>navigationGenerationCurrent(generation);
  const load=type==='performers'?loadAllPerformerScenes:loadAllStudioScenes;
  let total=0,rendered=false;
  async function reload(){
    const rows=await load(id,localId,generation);
    if(!current()||rows.cancelled)return;
    const openYears=new Set([...list.querySelectorAll('details[open] .profile-year-label')].map(el=>el.textContent));
    total=rows.items.length;list.innerHTML=sceneProfileList(rows.items);
    if(rendered)list.querySelectorAll('details.profile-year').forEach(el=>{el.open=openYears.has(el.querySelector('.profile-year-label')?.textContent)});
    rendered=true;bindProfileSceneLinks(list);
  }
  function countLabel(value,singular){
    const count=Number(value||0);
    return `${count.toLocaleString()} ${count===1?singular:`${singular}s`}`
  }
  function checkedAt(value){
    if(!value)return '';
    const date=new Date(value);
    return Number.isNaN(date.getTime())?'':` · Last successful check ${date.toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'})}`
  }
  function progress(result){
    return `${countLabel(result.pages_fetched,'page')} checked · ${countLabel(result.scenes_cached,'scene')} saved${checkedAt(result.last_success_at)}`
  }
  function failed(error,result=null){
    if(!current())return;
    const detail=error.message||error;
    status.textContent=result
      ?`Scene check failed · ${progress(result)} · ${detail}. Saved scenes remain available. Use Refresh scenes to retry.`
      :`Scene check failed — ${detail}. Saved scenes remain available. Use Refresh scenes to retry.`;
    button.disabled=false;button.textContent='Refresh scenes';
  }
  async function update(result,reloadScenes=true){
    if(!current())return;
    const active=['queued','running'].includes(result.status);
    button.disabled=active;button.textContent=active?'Checking scenes…':'Refresh scenes';
    if(active){
      status.textContent=result.status==='queued'
        ?`Scene check queued · ${progress(result)}`
        :`Scene check in progress · ${progress(result)}`;
      setTimeout(async()=>{if(!current())return;try{await update(await api(`/api/library/${type}/${localId}/scene-catalog`))}catch(e){failed(e)}},2000);
    }else{
      if(reloadScenes)await reload();
      if(!current())return;
      if(typeof entityLibraryCache!=='undefined')for(const key of ['scenes','performers','studios'])entityLibraryCache[key]=null;
      if(typeof entityPrefetch!=='undefined')entityPrefetch.clear();
      if(result.status==='failed')failed(result.error||'Provider unavailable',result);
      else if(result.status==='completed')status.textContent=`Scene check complete · ${progress(result)}`;
      else status.textContent=`Never checked · ${progress(result)}`;
    }
  }
  button.onclick=async()=>{
    if(!current())return;
    button.disabled=true;
    try{await update(await api(`/api/library/${type}/${localId}/refresh`,post({})))}catch(e){failed(e)}
  };
  try{
    await reload();
    if(!current())return;
    if(!localId){button.disabled=true;status.textContent='Could not save this profile locally. Reopen it to retry.';return}
    await update(await api(`/api/library/${type}/${localId}/scene-catalog`,post({})),false);
  }catch(e){failed(e)}
}

performerProfile=async function(id,localId=null){
  const generation=nextNavigationGeneration();
  $('#app').innerHTML=pageHead('Performer','Loading performer profile…',`<button class="btn" id="backPerformers">← Performers</button>`)+`<div class="empty">Loading performer information…</div>`;
  $('#backPerformers').onclick=()=>{view='performers';renderEntities('performers')};
  try{
    let local=null;
    if(localId){try{local=await api(`/api/library/performers/${encodeURIComponent(localId)}/detail`)}catch(_){}}
    else{try{local=await api(`/api/library/performers/by-tpdb/${encodeURIComponent(id)}/detail`)}catch(_){let cached=entityLibraryCache.performers?.items||[],summary=cached.find(v=>String(v.tpdb_id)===String(id))||null;if(summary?.id){try{local=await api(`/api/library/performers/${encodeURIComponent(summary.id)}/detail`)}catch(_){local=summary}}}}
    if(!navigationGenerationCurrent(generation))return;
    let resolvedLocalId=localId||local?.id||null;
    let x=local?localPerformerProfile(local):await api(`/api/metadata/performers/${encodeURIComponent(id)}`);
    // A remote search result is valid even when it is not in the local library.
    // Do not perform a second local-only lookup here: a 404 would leave the
    // profile stuck on its loading state after metadata already loaded.
    if(!navigationGenerationCurrent(generation))return;
    // The profile itself should be usable immediately.  Populate the potentially
    // large scene list afterward instead of blocking the entire page on it.
    let scenes={items:[]};
    if(!navigationGenerationCurrent(generation))return;
    let img=x.image_url?`/api/artwork/performers/${encodeURIComponent(id)}`:'';let links=Object.entries(x.links||{}).filter(([,v])=>v).map(([k,v])=>`<a class="btn small" target="_blank" rel="noopener" href="${esc(v)}">${esc(k)}</a>`).join('');
    $('#app').innerHTML=pageHead(x.name||'Performer','Cached performer profile',`<button class="btn" id="backPerformers">← Performers</button>${local?`<button class="btn ${local.monitored?'':'primary'}" id="togglePerformerMonitor">${local.monitored?'Unmonitor':'Monitor'}</button>`:`<button class="btn primary" id="monitorAllPerformer">Monitor All</button>`}`)+`<div class="profile-shell"><div class="profile-image">${img?`<img src="${esc(img)}" alt="${esc(x.name||'Performer')}" loading="eager" onerror="this.remove()">`:'No performer image available.'}</div><div><div class="profile-facts">${performerFacts(x,local?local.monitored:null)}</div>${x.bio?`<div class="profile-section"><h2>Biography</h2><div class="profile-bio">${esc(x.bio)}</div></div>`:''}${links?`<div class="profile-section"><h2>Links</h2><div class="profile-links">${links}</div></div>`:''}</div></div><div class="profile-section"><h2>Studio Scenes</h2><div id="performerSceneList">${sceneProfileList(scenes.items||[])}</div></div>`;
    $('#backPerformers').onclick=()=>{view='performers';renderEntities('performers')};if($('#togglePerformerMonitor'))$('#togglePerformerMonitor').onclick=async e=>{try{let next=await toggleEntityMonitor('performers',resolvedLocalId,local.monitored,e.currentTarget);local.monitored=next}catch(err){notify(err.message,'error')}};if($('#monitorAllPerformer'))$('#monitorAllPerformer').onclick=async e=>{try{await monitorAllEntity('performers',id,resolvedLocalId,e.currentTarget)}catch(err){notify(err.message,'error')}};
    initProfileSceneCatalog('performers',id,resolvedLocalId,generation);
  }catch(e){if(!navigationGenerationCurrent(generation))return;notify(e.message,'error');if(!navigationGenerationCurrent(generation))return;$('#app').innerHTML=pageHead('Performer','Unable to load performer profile.',`<button class="btn" id="backPerformers">← Performers</button>`)+empty(e.message);$('#backPerformers').onclick=()=>{view='performers';renderEntities('performers')}}
};

studioProfile=async function(id,localId=null){
  const generation=nextNavigationGeneration();
  $('#app').innerHTML=pageHead('Studio','Loading studio…',`<button class="btn" id="backStudios">← Studios</button>`)+empty('Loading studio information…');
  $('#backStudios').onclick=()=>{view='studios';renderEntities('studios')};
  try{
    let local=null;
    if(localId){try{local=await api(`/api/library/studios/${encodeURIComponent(localId)}/detail`)}catch(_){}}
    else{try{local=await api(`/api/library/studios/by-tpdb/${encodeURIComponent(id)}/detail`)}catch(_){let cached=entityLibraryCache.studios?.items||[],summary=cached.find(v=>String(v.tpdb_id)===String(id))||null;if(summary?.id){try{local=await api(`/api/library/studios/${encodeURIComponent(summary.id)}/detail`)}catch(_){local=summary}}}}
    if(!navigationGenerationCurrent(generation))return;
    let resolvedLocalId=localId||local?.id||null;
    let x=local?{...local,id:local.tpdb_id}:await api(`/api/metadata/studios/${encodeURIComponent(id)}`);
    // A remote search result is valid even when it is not in the local library.
    // Do not perform a second local-only lookup after remote metadata loads.
    if(!navigationGenerationCurrent(generation))return;
    let scenes={items:[]};
    if(!navigationGenerationCurrent(generation))return;
    $('#app').innerHTML=pageHead(x.name||'Studio','Cached studio profile',`<button class="btn" id="backStudios">← Studios</button>${local?`<button class="btn ${local.monitored?'':'primary'}" id="toggleStudioMonitor">${local.monitored?'Unmonitor':'Monitor'}</button>`:`<button class="btn primary" id="monitorAllStudio">Monitor All</button>`}`)+`<div class="profile-facts"><div class="profile-fact"><b>Monitored</b><span>${local?.monitored?'Yes':'No'}</span></div>${x.url?`<div class="profile-fact"><b>Website</b><span><a target="_blank" rel="noopener" href="${esc(x.url)}">Open site</a></span></div>`:''}</div>${x.description?`<div class="profile-section"><h2>About</h2><div class="profile-bio">${esc(x.description)}</div></div>`:''}<div class="profile-section"><h2>Studio Scenes</h2><div id="studioSceneList">${sceneProfileList(scenes.items||[])}</div></div>`;
    $('#backStudios').onclick=()=>{view='studios';renderEntities('studios')};if($('#toggleStudioMonitor'))$('#toggleStudioMonitor').onclick=async e=>{try{let next=await toggleEntityMonitor('studios',resolvedLocalId,local.monitored,e.currentTarget);local.monitored=next}catch(err){notify(err.message,'error')}};if($('#monitorAllStudio'))$('#monitorAllStudio').onclick=async e=>{try{await monitorAllEntity('studios',id,resolvedLocalId,e.currentTarget)}catch(err){notify(err.message,'error')}};bindProfileSceneLinks($('#studioSceneList'));
    initProfileSceneCatalog('studios',id,resolvedLocalId,generation);
  }catch(e){if(!navigationGenerationCurrent(generation))return;notify(e.message,'error');if(!navigationGenerationCurrent(generation))return;$('#app').innerHTML=pageHead('Studio','Unable to load studio.',`<button class="btn" id="backStudios">← Studios</button>`)+empty(e.message);$('#backStudios').onclick=()=>{view='studios';renderEntities('studios')}}
};
