(() => {
  const baseActivityQueueHtml=activityQueueHtml;
  const baseApplyLiveQueue=applyLiveQueue;

  function studioLine(value){
    return `<small class="live-studio" style="display:block;margin-top:2px">${value?esc(value):''}</small>`;
  }

  activityQueueHtml=function(rows){
    let index=0;
    return baseActivityQueueHtml(rows).replace(/(<b class="live-title">[\s\S]*?<\/b>)/g,match=>{
      const x=rows[index++]||{};
      return `${match}${studioLine(x.studio)}`;
    });
  };

  function syncStudioLabels(rows){
    const byId=new Map((rows||[]).map(x=>[String(x.external_id||''),x]));
    document.querySelectorAll('[data-live-job]').forEach(row=>{
      const x=byId.get(String(row.dataset.liveJob||''));
      if(!x)return;
      let label=row.querySelector('.live-studio');
      if(!label){
        label=document.createElement('small');
        label.className='live-studio';
        label.style.display='block';
        label.style.marginTop='2px';
        row.querySelector('.live-title')?.insertAdjacentElement('afterend',label);
      }
      label.textContent=x.studio||'';
    });
  }

  applyLiveQueue=function(q){
    baseApplyLiveQueue(q);
    const snapshotRows=q?.tracked||[];
    const visibleRows=activityQueuePage===1?snapshotRows.slice(0,ACTIVITY_QUEUE_PAGE_SIZE):activityQueuePageRows;
    syncStudioLabels(visibleRows);
  };
})();
