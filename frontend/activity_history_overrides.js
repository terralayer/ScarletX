(() => {
  const baseActivity=activity;
  const ACTIVITY_HISTORY_PAGE_SIZE=50;
  let activityHistoryPage=1;
  let activityHistoryEventType='';
  let activityHistoryRequest=0;

  function historyPageUrl(){
    const filter=activityHistoryEventType?`&event_type=${encodeURIComponent(activityHistoryEventType)}`:'';
    return `/api/history/page?page=${activityHistoryPage}&limit=${ACTIVITY_HISTORY_PAGE_SIZE}${filter}`;
  }

  function historyFilterOptions(payload){
    const counts=payload?.event_counts||{};
    const total=Number(payload?.total||0);
    const rows=[`<option value="">All (${total})</option>`];
    Object.keys(counts).sort().forEach(kind=>{
      const selected=kind===activityHistoryEventType?' selected':'';
      rows.push(`<option value="${esc(kind)}"${selected}>${esc(kind)} (${Number(counts[kind]||0)})</option>`);
    });
    return rows.join('');
  }

  function renderHistoryControls(payload){
    const host=$('#activityHistory');
    if(!host)return;
    const total=Number(payload?.total||0);
    const pages=Math.max(1,Math.ceil(total/ACTIVITY_HISTORY_PAGE_SIZE));
    const controls=document.createElement('div');
    controls.className='history-controls actions';
    controls.style.marginBottom='12px';
    controls.innerHTML=`<label>Event <select id="activityHistoryFilter">${historyFilterOptions(payload)}</select></label><span class="muted">${total} event${total===1?'':'s'}</span>`;
    host.prepend(controls);
    host.insertAdjacentHTML('beforeend',activityPager('history',activityHistoryPage,total,ACTIVITY_HISTORY_PAGE_SIZE));

    $('#activityHistoryFilter').onchange=e=>{
      activityHistoryEventType=e.target.value||'';
      activityHistoryPage=1;
      activity();
    };
    host.onclick=e=>{
      const button=e.target.closest('[data-activity-page="history"]');
      if(!button||button.disabled)return;
      const next=Number(button.dataset.page)||1;
      activityHistoryPage=Math.min(Math.max(1,next),pages);
      activity();
    };
  }

  activity=async function(){
    const requestId=++activityHistoryRequest;
    const originalFetch=window.fetch;
    let payload=null;

    window.fetch=async (input,init)=>{
      const url=typeof input==='string'?input:input?.url;
      if(url!=='/api/history?limit=200')return originalFetch.call(window,input,init);

      const response=await originalFetch.call(window,historyPageUrl(),init);
      if(!response.ok)return response;
      payload=await response.clone().json();
      return new Response(JSON.stringify(payload.items||[]),{
        status:response.status,
        statusText:response.statusText,
        headers:{'Content-Type':'application/json'},
      });
    };

    try{
      await baseActivity();
    }finally{
      window.fetch=originalFetch;
    }

    if(requestId!==activityHistoryRequest||view!=='activity'||!payload)return;
    const pages=Math.max(1,Math.ceil(Number(payload.total||0)/ACTIVITY_HISTORY_PAGE_SIZE));
    if(activityHistoryPage>pages){
      activityHistoryPage=pages;
      return activity();
    }
    renderHistoryControls(payload);
  };
})();
