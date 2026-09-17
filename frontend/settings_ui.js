/* Presentation for the existing settings forms. Fields are moved, never cloned,
   so the API payloads and credential-preservation behavior stay in app.js. */
function settingsNavigation(tabs) {
  const groups = [['Application', ['general','media']], ['Connections', ['metadata','indexers','downloads']], ['Maintenance', ['automation','backups']], ['Administration', ['security','system']]];
  return groups.map(([title, ids]) => `<div class="settings-nav-group"><div class="settings-nav-label">${title}</div>${ids.map(id => {const label=tabs.find(t=>t[0]===id)[1];return `<button data-tab="${id}" class="${settingsTab===id?'active':''}" aria-current="${settingsTab===id?'page':'false'}">${label}</button>`}).join('')}</div>`).join('');
}
function enhanceSettings(tab, body) {
  if (!body?.isConnected) return;
  const original=body.querySelector('.settings-panel');
  if (!original) return;
  const descriptions={general:['General','Make ScarletX your own.'],metadata:['TPDB','Connect your scene, performer, and studio metadata.'],indexers:['Indexers','Manage sources for scene search and RSS.'],downloads:['Download Client','Fine-tune transfers, folders, and Usenet providers.'],media:['Media Management','Choose where your library lives and how files are organized.'],automation:['Automation','Keep your library up to date automatically.'],backups:['Backups','Schedule database backups and manage retention.'],security:['Security','Manage browser sign-in and integration access.'],system:['System','Check runtime health and available storage.']};
  const [title,description]=descriptions[tab];
  const header=document.createElement('header');header.className='settings-page-heading';
  header.innerHTML=`<span class="settings-eyebrow">SETTINGS</span><h2>${title}</h2><p>${description}</p>`;
  body.prepend(header);
  const section=(title,description,selectors)=>{
    const panel=document.createElement('section');panel.className='settings-section';
    panel.innerHTML=`<header><h3>${title}</h3><p>${description}</p></header><div class="settings-fields"></div>`;
    const fields=panel.lastElementChild;
    selectors.forEach(selector=>{const node=original.querySelector(selector);if(node)fields.append(node.closest('.field')||node)});
    body.append(panel);return fields;
  };
  if(tab==='general'){
    section('Application','The name shown throughout your workspace.',['#appName']);
    section('Logging','Control the detail recorded in application logs.',['#logLevel']);
  }else if(tab==='metadata') section('ThePornDB connection','Use your API credentials to retrieve metadata.',['#tpdbKey','#tpdbUrl']);
  else if(tab==='indexers') section('Newznab indexers','Add an indexer to start searching for releases.',['#addIndexer','#indexers']);
  else if(tab==='downloads'){
    section('Transfers','Control download performance and bandwidth.',['#nativeEnabled','#nativeConnections','#nativeRetries','#nativeSpeed']);
    section('Download folders','Keep active transfers separate from completed downloads.',['#nativeIncomplete','#nativeComplete']);
    section('Usenet providers','Connect your encrypted NNTP accounts.',['#addProvider','#providers']);
    const hint=original.querySelector('.tool-grid + p');
    section('Post-processing','Repair and extract downloads automatically.',['#nativeRepair','#nativeUnpack','.tool-grid']);
    if(hint)body.lastElementChild.lastElementChild.append(hint);
  }else if(tab==='media'){
    section('Library folders','Choose an absolute path for your scene library.',['#sceneRoot']);
    section('File organization','Control imports and file naming.',['#fileEnabled','#importMode','#sceneTemplate']);
    section('Storage safeguards','Set your recycle folder and free-space threshold.',['#recycleBin','#minFree']);
  }else if(tab==='automation'){
    section('Automatic search','Search for monitored scenes on a schedule.',['#autoEnabled','#autoInterval','#autoBatch']);
    section('RSS sync','Check indexers for new releases.',['#rssEnabled','#rssInterval','#rssMax','#rssGrab']);
  }else if(tab==='backups'){
    section('Scheduled backups','Keep rotating copies of your SQLite database.',['#backupEnabled','#backupDir','#backupHours','#backupKeep']);
    section('Manual backup','Create a database backup now.',['#backupNow']);
  }else if(tab==='security'){
    section('Browser sign-in','Protect access to the ScarletX browser interface.',['#uiAuthEnabled','#securityUsername','#securityPassword','#securityPasswordConfirm']);
    section('API access','Configure an integration credential for use with browser authentication.',['#apiEnabled','#apiKey']);
  }else if(tab==='system') section('Runtime and storage','Current application status and scene root capacity.',['#systemSettings']);
  const save=original.querySelector('button.primary');
  if(save){
    const footer=document.createElement('footer');footer.className='settings-savebar';
    footer.innerHTML='<span>Changes apply when you save.</span><div><button class="btn" id="resetSettings">Reset</button></div>';
    save.textContent='Save changes';footer.lastElementChild.append(save);body.append(footer);
    const reset=footer.querySelector('#resetSettings');
    reset.onclick=()=>settings();
    const handler=save.onclick;
    save.onclick=async event=>{save.disabled=true;reset.disabled=true;try{await handler(event)}catch(error){notify(error.message,'error')}finally{save.disabled=false;reset.disabled=false}};
  }
  original.remove();
  body.querySelector('#nativeSpeed')?.closest('.field').classList.add('span2');
  body.querySelectorAll('.field').forEach(field=>{
    const control=field.querySelector('input,select');const label=field.querySelector('label');
    if(control&&label&&control.id)label.htmlFor=control.id;
  });
  body.querySelectorAll('select[id]').forEach(select=>{
    if(select.options.length!==2||![...select.options].every(o=>['true','false'].includes(o.value)))return;
    const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.id=select.id+'Toggle';checkbox.className='settings-switch';checkbox.checked=select.value==='true';
    const field=select.closest('.field'),label=field.querySelector('label');label.htmlFor=checkbox.id;
    select.hidden=true;select.after(checkbox);field.classList.add('settings-toggle-field');
    checkbox.onchange=()=>{select.value=String(checkbox.checked);select.dispatchEvent(new Event('change',{bubbles:true}))};
  });
  for(const [id,label] of [['providers','providers'],['indexers','indexers']]){
    const collection=body.querySelector('#'+id);if(!collection)continue;
    const empty=document.createElement('div');empty.className='settings-empty';empty.textContent=`No ${label} configured. Add one to get started.`;collection.before(empty);
    const refresh=()=>{empty.hidden=collection.children.length>0;collection.querySelectorAll('.field').forEach(field=>{const c=field.querySelector('input,select'),l=field.querySelector('label');if(c&&l)c.setAttribute('aria-label',l.textContent.trim())})};
    refresh();const observer=new MutationObserver(refresh);observer.observe(collection,{childList:true});
  }
}
