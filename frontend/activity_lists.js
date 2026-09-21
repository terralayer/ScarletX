// Each download list fetches and renders independently; no global fetch interception.
const activitySections={
  completed:{page:1,request:0,size:()=>ACTIVITY_COMPLETED_PAGE_SIZE},
  failed:{page:1,request:0,size:()=>ACTIVITY_FAILED_PAGE_SIZE},
  history:{page:1,request:0,size:()=>15,filter:''},
};
function activitySectionHost(kind){return $('#activity'+kind[0].toUpperCase()+kind.slice(1))}
function activitySectionUrl(kind,state){
  if(kind==='history')return `/api/history/page?page=${state.page}&limit=${state.size()}`+(state.filter?`&event_type=${encodeURIComponent(state.filter)}`:'');
  return `/api/downloads/${kind}?limit=${state.size()}&offset=${(state.page-1)*state.size()}`;
}
function activityCompletedHtml(completed){return (completed.length?`<div class="tablewrap" style="border:0;border-radius:0"><table class="table"><thead><tr><th>Scene</th><th>Size</th><th>Completed</th><th>Import</th><th>Post-processing</th><th></th></tr></thead><tbody>${completed.map(x=>`<tr><td><b>${esc(x.scene_title||x.release_title||x.title||'Download')}</b></td><td>${bytes(x.total_bytes||x.downloaded_bytes||0)}</td><td>${fmtDate(x.completed_at)}</td><td><span class="state ${x.imported_at?'good':'warn'}">${x.imported_at?'Imported':'Awaiting import'}</span></td><td><small>${esc(x.postprocess_note||'Download complete')}</small></td><td>${x.imported_at?'':`<button class="btn small primary" data-reprocess-completed data-job="${esc(x.id)}">Reprocess</button>`}</td></tr>`).join('')}</tbody></table></div>`:empty('No completed downloads yet.'))}
function activityFailedHtml(failed){return (failed.length?`<div class="tablewrap" style="border:0;border-radius:0"><table class="table"><thead><tr><th>Scene</th><th>Failure</th><th>Partial</th><th></th></tr></thead><tbody>${failed.map(x=>`<tr><td><b>${esc(x.title||'Download')}</b></td><td><span class="state bad">Failed</span><small>${esc(x.error||'Download failed')}</small></td><td>${bytes(x.downloaded_bytes||0)} / ${x.total_bytes?bytes(x.total_bytes):'—'}</td><td><div class="actions"><button class="btn small primary" data-failed-retry data-job="${esc(x.id)}">Retry</button><button class="btn small" data-native-password data-job="${esc(x.id)}">Archive Password</button></div></td></tr>`).join('')}</tbody></table></div>`:empty('No failed downloads.'))}
function activityHistoryRowsHtml(h){return h.length?`<div class="tablewrap" style="border:0;border-radius:0"><table class="table"><thead><tr><th>Event</th><th>Message</th><th>Date</th></tr></thead><tbody>${h.map(x=>`<tr><td>${esc(x.event_type)}</td><td>${esc(x.message)}</td><td>${fmtDate(x.created_at)}</td></tr>`).join('')}</tbody></table></div>`:empty('No history yet.')}

function historyFilterHtml(data,state){
  const counts=data.event_counts||{},all=Object.values(counts).reduce((sum,n)=>sum+Number(n),0);
  const options=Object.keys(counts).sort().map(kind=>`<option value="${esc(kind)}" ${kind===state.filter?'selected':''}>${esc(kind)} (${counts[kind]})</option>`).join('');
  return `<div class="history-controls actions"><label>Event <select id="activityHistoryFilter"><option value="">All (${all})</option>${options}</select></label><span class="muted">${Number(data.total||0)} events</span></div>`;
}
async function loadActivitySection(kind){
  const state=activitySections[kind],host=activitySectionHost(kind),request=++state.request,requestedPage=state.page,filter=state.filter;
  if(!host)return false;
  let page=requestedPage;
  while(true){
    const data=await api(activitySectionUrl(kind,{...state,page}));
    if(view!=='activity'||activitySectionHost(kind)!==host||request!==state.request||requestedPage!==state.page||filter!==state.filter)return false;
    const rows=kind==='history'?(data.items||[]):(data.scarletx||[]),total=Number(data.total??rows.length),pages=Math.max(1,Math.ceil(total/state.size()));
    if(page>pages){page=pages;continue}
    state.page=page;
    host.innerHTML=(kind==='completed'?activityCompletedHtml(rows):kind==='failed'?activityFailedHtml(rows):historyFilterHtml(data,state)+activityHistoryRowsHtml(rows))+activityPager(kind,page,total,state.size());
    bindActivitySection(kind,host);
    return true;
  }
}
function changeActivitySectionPage(kind,page){
  const state=activitySections[kind],host=activitySectionHost(kind);
  return changeListPage({host,page,getPage:()=>state.page,setPage:value=>state.page=value,
    load:()=>loadActivitySection(kind),current:()=>view==='activity'&&activitySectionHost(kind)===host});
}
function bindActivitySection(kind,host){
  const filter=host.querySelector('#activityHistoryFilter');
  if(filter)filter.onchange=async event=>{
    const state=activitySections.history,oldFilter=state.filter,oldPage=state.page;
    state.filter=event.target.value||'';state.page=1;filter.disabled=true;
    try{await loadActivitySection('history')}catch(error){
      if(activitySectionHost('history')===host&&view==='activity'){state.filter=oldFilter;state.page=oldPage;filter.value=oldFilter;notify(error.message,'error')}
    }finally{filter.disabled=false}
  };
  host.onclick=async event=>{
    const pager=event.target.closest('[data-activity-page]');
    if(pager){if(!pager.disabled)return changeActivitySectionPage(kind,Number(pager.dataset.page));return}
    const retry=event.target.closest('[data-section-retry]');
    if(retry){try{await loadActivitySection(kind)}catch(error){notify(error.message,'error')}return}
    const button=event.target.closest('[data-reprocess-completed],[data-failed-retry],[data-native-password]');
    if(!button||button.disabled)return;
    const id=encodeURIComponent(button.dataset.job);
    button.disabled=true;
    try{
      if(button.hasAttribute('data-native-password')){
        const password=prompt('Archive password for this download:','');if(password===null)return;
        await api(`/api/downloads/native/${id}/password`,post({password}));notify('Archive password saved.','ok');
      }else{
        const action=button.hasAttribute('data-reprocess-completed')?'reprocess':'resume';
        await api(`/api/downloads/native/${id}/${action}`,post());
        notify(action==='reprocess'?'Completed payload reprocessed. Import will run automatically.':'Failed download moved back to the queue.','ok');
        if(view==='activity'&&activitySectionHost(kind)===host)await loadActivitySection(kind);
        await resyncLiveQueue();
      }
    }catch(error){notify(error.message,'error')}finally{button.disabled=false}
  };
}
async function initializeActivityLists(){
  await Promise.all(Object.keys(activitySections).map(async kind=>{
    const host=activitySectionHost(kind);if(!host)return;
    host.innerHTML=empty('Loading…');
    try{await loadActivitySection(kind)}catch(error){
      if(view==='activity'&&activitySectionHost(kind)===host){
        host.innerHTML=empty(error.message)+'<button class="btn small" data-section-retry>Retry</button>';
        bindActivitySection(kind,host);
      }
    }
  }));
}
