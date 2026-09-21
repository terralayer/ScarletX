/* Management tools reuse the existing settings forms and authenticated API. */
(() => {
  const formatDate = value => value ? new Date(value).toLocaleString() : 'None yet';
  const connectionTargets={metadata:'#tpdbKey',indexers:'#indexers',downloads:'#nativeEnabled'};
  const goSettings = async tab => { view='settings'; settingsTab=tab; nav(); await settings(); const target=document.querySelector(connectionTargets[tab]); if(target){target.scrollIntoView({behavior:'smooth',block:'center'});target.focus?.();} };
  const section = (body,title,description) => {
    const panel=document.createElement('section');panel.className='settings-section management-panel';
    panel.innerHTML=`<header><h3>${esc(title)}</h3><p>${esc(description)}</p></header><div class="management-body" aria-live="polite">Loading…</div>`;
    body.insertBefore(panel,body.querySelector('.settings-savebar'));return panel.lastElementChild;
  };
  const showError = (body,error) => {if(body.isConnected)body.textContent=error.message||'Could not load this panel.';};
  let connectionResults={};
  try {connectionResults=JSON.parse(sessionStorage.getItem('scarletxConnectionChecks')||'{}')} catch (_) {}
  const persistChecks=()=>{try{sessionStorage.setItem('scarletxConnectionChecks',JSON.stringify(connectionResults))}catch(_){}};
  async function wizard(body) {
    const data=await api('/api/operations/connections');
    if(!body.isConnected||!Array.isArray(data.steps))return;
    const panel=document.createElement('section');panel.className='settings-section connection-wizard';panel.id='connectionWizard';
    const allPassed=data.steps.every(step=>step.configured&&connectionResults[step.id]===step.revision);
    panel.innerHTML=`<header><h3>Connection setup ${allPassed?'· Complete':''}</h3><p>Save each connection in its settings page, then test it here. Tests use your saved credentials.</p></header><div class="connection-steps">${data.steps.map((step,i)=>{
      const passed=step.configured&&connectionResults[step.id]===step.revision;
      return `<article><small>STEP ${i+1}</small><h4>${esc(step.title)}</h4><p class="connection-result">${passed?'Connection tested':step.configured?'Saved · test needed':'Not configured'}</p><div class="actions"><button class="btn" data-configure="${esc(step.id)}">Configure</button><button class="btn" data-test-connection="${esc(step.id)}" ${step.configured?'':'disabled'}>Test saved connection</button></div></article>`;
    }).join('')}</div>`;
    body.querySelector('#connectionWizard')?.remove();const heading=body.querySelector('.settings-page-heading');if(heading)heading.after(panel);else body.prepend(panel);
    panel.querySelectorAll('[data-configure]').forEach(button=>button.onclick=()=>goSettings(button.dataset.configure));
    panel.querySelectorAll('[data-test-connection]').forEach(button=>button.onclick=async()=>{
      const kind=button.dataset.testConnection,result=button.closest('article').querySelector('.connection-result');
      button.disabled=true;result.textContent='Testing…';delete connectionResults[kind];persistChecks();
      try {
        const response=await api(`/api/operations/connections/${kind}/test`,post());
        if(!response.ok)throw new Error('Connection test did not pass.');
        connectionResults[kind]=response.revision;
        persistChecks();
        if(body.isConnected)await wizard(body);
      } catch(error) {if(result.isConnected)result.textContent=error.message;} finally {if(button.isConnected)button.disabled=false;}
    });
  }
  async function storage(body) {
    const slot=section(body,'Storage overview','Folder size and filesystem capacity are separate measurements.');
    const refresh=async()=>{
      slot.textContent='Checking storage…';
      try {
        const result=await api('/api/operations/storage');if(!slot.isConnected)return;
        slot.innerHTML=`<div class="management-toolbar"><p>${esc(result.note||'')}</p><button class="btn" data-refresh-storage>Refresh</button></div><div class="storage-grid">${(result.items||[]).map(row=>{
          const percent=row.total_bytes?Math.max(0,Math.min(100,100*row.used_bytes/row.total_bytes)):0;
          return `<article class="management-storage-card"><h4>${esc(row.name)}</h4><p class="storage-path">${esc(row.path)}</p><b>${row.free_bytes==null?'Unavailable':bytes(row.free_bytes)+' free'}</b><div class="storage-meter" role="meter" aria-label="Filesystem used" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(percent)}"><span style="width:${percent}%"></span></div><p>Filesystem: ${row.total_bytes==null?'unavailable':bytes(row.used_bytes)+' used / '+bytes(row.total_bytes)+' total'}</p><p>Folder: ${row.folder?.bytes==null?'unavailable':(row.folder.complete?'':'at least ')+bytes(row.folder.bytes)}</p>${row.folder?.error?`<small>${esc(row.folder.error)}</small>`:''}</article>`;
        }).join('')}</div>`;
        slot.querySelector('[data-refresh-storage]').onclick=refresh;
      } catch(error){showError(slot,error)}
    };await refresh();
  }
  async function backup(body) {
    const slot=section(body,'Backup reminder','Keep the database and matching installation key together when restoring.');
    const refresh=async()=>{try{
      const result=await api('/api/operations/backup-reminder');if(!slot.isConnected)return;
      slot.innerHTML=`<p class="state ${result.state==='healthy'?'good':'warn'}">${esc(result.message||'Backup status unavailable')}</p><p>Last successful backup: ${esc(formatDate(result.last_success_at))}</p><p>Next due: ${result.enabled?esc(formatDate(result.next_due_at)):'Automatic backups are off'}</p>`;
    }catch(error){showError(slot,error)}};
    const button=body.querySelector('#backupNow');if(button){const original=button.onclick;button.onclick=async event=>{button.disabled=true;try{await original(event);await refresh()}finally{button.disabled=false}}}
    await refresh();
  }
  async function schedule(body) {
    const slot=section(body,'Download schedule','Daily quiet hours pause transfers or cap their speed. Manual pauses stay paused; post-processing may finish.');
    try {
      const data=await api('/api/operations/download-schedule');if(!slot.isConnected||!data.rule)return;
      const rule=data.rule;
      slot.innerHTML=`<form id="downloadScheduleForm"><div class="formgrid"><div class="field"><label for="scheduleEnabled">Quiet hours</label><select id="scheduleEnabled"><option value="false" ${!rule.enabled?'selected':''}>Disabled</option><option value="true" ${rule.enabled?'selected':''}>Enabled</option></select></div><div class="field"><label for="scheduleTimezone">Timezone</label><input class="input" id="scheduleTimezone" value="${esc(rule.timezone)}" required><button class="linkbtn" type="button" id="scheduleLocalTimezone">Use browser timezone</button></div><div class="field"><label for="scheduleStart">Start</label><input class="input" id="scheduleStart" type="time" value="${esc(rule.start)}" required></div><div class="field"><label for="scheduleEnd">End</label><input class="input" id="scheduleEnd" type="time" value="${esc(rule.end)}" required></div><div class="field"><label for="scheduleMode">During quiet hours</label><select id="scheduleMode"><option value="pause" ${rule.mode==='pause'?'selected':''}>Pause transfers</option><option value="limit" ${rule.mode==='limit'?'selected':''}>Limit speed</option></select></div><div class="field"><label for="scheduleSpeed">Speed cap (MiB/s)</label><input class="input" id="scheduleSpeed" type="number" min="0.01" max="10000" step="0.01" value="${rule.speed_limit_mb_s}"></div></div><p id="scheduleStatus">${data.state?.active?'Quiet hours are active.':'Quiet hours are inactive.'} Times use ${esc(rule.timezone)}.</p><button class="btn primary" type="submit">Save schedule</button><span id="scheduleResult" role="status"></span></form>`;
      const form=slot.querySelector('form');const input=id=>form.querySelector('#'+id);
      input('scheduleLocalTimezone').onclick=()=>{input('scheduleTimezone').value=Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC'};
      form.onsubmit=async event=>{
        event.preventDefault();const button=form.querySelector('[type=submit]'),message=input('scheduleResult');button.disabled=true;message.textContent='';
        const payload={enabled:input('scheduleEnabled').value==='true',timezone:input('scheduleTimezone').value.trim(),start:input('scheduleStart').value,end:input('scheduleEnd').value,mode:input('scheduleMode').value,speed_limit_mb_s:Number(input('scheduleSpeed').value)};
        try{const result=await api('/api/operations/download-schedule',patch(payload));if(form.isConnected){message.textContent='Schedule saved.';input('scheduleStatus').textContent=`${result.state?.active?'Quiet hours are active.':'Quiet hours are inactive.'} Times use ${payload.timezone}.`;}}catch(error){if(form.isConnected)message.textContent=error.message}finally{if(button.isConnected)button.disabled=false}
      };
    }catch(error){showError(slot,error)}
  }
  const originalEnhance=window.enhanceSettings;
  window.enhanceSettings=(tab,body)=>{
    originalEnhance(tab,body);
    if(['general','metadata','indexers','downloads'].includes(tab))wizard(body).catch(()=>{});
    if(tab==='system')storage(body);
    if(tab==='backups')backup(body);
    if(tab==='downloads')schedule(body);
  };
  const originalLibrary=window.mediaLibrary;
  window.mediaLibrary=async function(){
    await originalLibrary();if(view!=='library')return;
    const anchor=document.querySelector('#libraryHealth')||document.querySelector('#libraryStats');if(!anchor)return;
    const panel=document.createElement('section');panel.className='panel cleanup-preview';panel.id='cleanupPreview';
    panel.innerHTML='<div class="panel-head"><h2>Library cleanup preview</h2><button class="btn" id="openCleanup">Review library</button></div><div class="management-body" id="cleanupResults" hidden></div>';
    anchor.after(panel);let category='duplicates',offset=0,request=0;
    const load=async()=>{
      const generation=++request,slot=panel.querySelector('#cleanupResults');slot.hidden=false;slot.textContent='Loading preview…';
      try{const data=await api(`/api/operations/cleanup?category=${category}&limit=25&offset=${offset}`);if(!panel.isConnected||generation!==request)return;
        slot.innerHTML=`<div class="actions">${[['duplicates','Potential duplicates'],['missing','Missing files'],['unmatched','Unmatched files']].map(([key,label])=>`<button class="btn ${category===key?'primary':''}" data-cleanup-category="${key}">${label}</button>`).join('')}</div><p>${esc(data.note||'Read-only preview. Nothing is changed.')}</p><div class="tablewrap"><table class="table"><thead><tr><th>Item</th><th>Path</th></tr></thead><tbody>${(data.items||[]).map(row=>`<tr><td>${esc(row.title||'Media file')}</td><td class="storage-path">${esc(row.path)}</td></tr>`).join('')}</tbody></table></div>${!(data.items||[]).length?'<p>No items to review in this category.</p>':''}<div class="actions"><button class="btn" data-cleanup-previous ${offset===0?'disabled':''}>Previous</button><button class="btn" data-cleanup-next ${data.has_more?'':'disabled'}>Next</button></div>`;
        slot.querySelectorAll('[data-cleanup-category]').forEach(button=>button.onclick=()=>{category=button.dataset.cleanupCategory;offset=0;load()});
        slot.querySelector('[data-cleanup-previous]').onclick=()=>{offset=Math.max(0,offset-25);load()};slot.querySelector('[data-cleanup-next]').onclick=()=>{offset+=25;load()};
      }catch(error){if(generation===request)showError(slot,error)}
    };panel.querySelector('#openCleanup').onclick=load;
  };
  const originalDashboard=window.dashboard;
  let dashboardGeneration=0;
  if(originalDashboard)window.dashboard=async function(){
    const generation=++dashboardGeneration;
    const reminder=api('/api/operations/backup-reminder').catch(()=>null);await originalDashboard();const data=await reminder;
    if(generation!==dashboardGeneration||view!=='dashboard'||!data||!['never','overdue','missing'].includes(data.state))return;
    const panel=document.createElement('div');panel.className='backup-reminder';panel.innerHTML=`<span>${esc(data.message)}</span><button class="btn">Review backups</button>`;panel.querySelector('button').onclick=()=>goSettings('backups');document.querySelector('#app').append(panel);
  };
})();
