const baseDashboardRender=dashboard;
dashboard=async function(){
  await baseDashboardRender();
  if(view!=='dashboard')return;
  try{
    let recent=await api('/api/dashboard/scenes?limit=8');
    if(view!=='dashboard')return;
    let scenes=recent.items||[];
    let sceneStat=[...document.querySelectorAll('#stats .stat')].find(card=>card.querySelector('small')?.textContent==='Scenes');
    if(sceneStat){
      let value=sceneStat.querySelector('strong'),detail=sceneStat.querySelector('em');
      if(value)value.textContent=String(Number(recent.total||0));
      if(detail)detail.textContent='Downloaded';
    }
    let recentRoot=$('#recentScenes');
    if(recentRoot){
      recentRoot.innerHTML=scenes.length?sceneTable(scenes,true):empty('No downloaded scenes yet.');
      bindSceneTableActions(recentRoot,true);
    }
  }catch(err){notify(err.message,'error')}
};

const baseRenderSettingsTab=renderSettingsTab;
renderSettingsTab=async function(){
  if(settingsTab!=='general')return baseRenderSettingsTab();
  let s=settingsCache,el=$('#settingsBody');
  el.innerHTML=`<div class="settings-panel"><h2>General</h2><p>ScarletX logging settings.</p><div class="formgrid"><div class="field"><label>Log level</label><select id="logLevel">${['DEBUG','INFO','WARNING','ERROR'].map(x=>`<option ${s.general.log_level===x?'selected':''}>${x}</option>`).join('')}</select></div></div><div class="divider"></div><button class="btn primary" id="saveGeneral">Save</button></div>`;
  $('#saveGeneral').onclick=()=>saveSetting('/api/settings/general',{log_level:val('#logLevel')});
};
