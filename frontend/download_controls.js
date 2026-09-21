// Persistent server state owns the toolbar, independent of the visible queue page.
let downloadControlState=null,downloadControlPending=false,downloadControlRequest=0;
function downloadToolbarAction(q){
  if(downloadControlState?.paused)return'resume';
  const states=(q?.tracked||[]).map(x=>x.client_status||x.status||x.native_job?.status);
  return !states.some(s=>['queued','downloading'].includes(s))&&states.includes('paused')?'resume':'pause';
}
function syncDownloadPauseControl(q=liveQueueSnapshot){
  const button=$('#pauseDownloader');if(!button)return;
  if(downloadControlPending){button.disabled=true;return}
  if(downloadControlState===null){button.disabled=false;button.textContent='Retry download status';button.dataset.downloadAction='refresh';return}
  const action=downloadToolbarAction(q);button.dataset.downloadAction=action;button.disabled=false;
  button.textContent=action==='resume'?'Resume Downloads':'Pause Downloads';
}
async function refreshDownloadControl(){
  const request=++downloadControlRequest;
  try{
    const state=await api('/api/downloads/native/control');
    if(request!==downloadControlRequest)return false;
    downloadControlState=state;syncDownloadPauseControl();return true;
  }catch(error){if(request===downloadControlRequest){notify(error.message,'error');syncDownloadPauseControl()}return false}
}
async function toggleAllNativeDownloads(e){
  if(downloadControlPending)return;
  if(downloadControlState===null||e.currentTarget.dataset.downloadAction==='refresh'){await refreshDownloadControl();return}
  const button=e.currentTarget,action=button.dataset.downloadAction||downloadToolbarAction(liveQueueSnapshot);
  downloadControlPending=true;++downloadControlRequest;button.disabled=true;button.textContent=action==='resume'?'Resuming…':'Pausing…';
  try{
    const result=await api(`/api/downloads/native/${action==='resume'?'resume-all':'pause-all'}`,post());
    downloadControlState={paused:result.global_paused??action!=='resume'};
    await resyncLiveQueue();
    notify(action==='resume'?`Resumed ${result.resumed||0} downloads.`:`Downloads paused. New downloads will wait until you resume.`, 'ok');
  }catch(error){notify(error.message,'error')}
  finally{downloadControlPending=false;syncDownloadPauseControl()}
}
async function clearAllDownloads(e){
  const button=e.currentTarget;
  if(!confirm('Clear all downloads? This will cancel active downloads, delete download staging files, and remove download history. Imported media files will not be touched.'))return;
  button.disabled=true;button.textContent='Clearing…';
  try{
    const result=await api('/api/downloads',{method:'DELETE'});
    notify(`Cleared ${result.cleared||0} download${result.cleared===1?'':'s'}${result.cancelled?`; cancelled ${result.cancelled}.`:'.'}`,'ok');
    await activity();
  }catch(error){notify(error.message,'error');button.disabled=false;button.textContent='Clear All Downloads'}
}
