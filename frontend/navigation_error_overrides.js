loadEntityLibrary=async function(type,cursor=null,append=false,q=null){
  try{
    if(q===null)q=entityLibraryQuery[type]||'';
    if(!append)entityLibraryQuery[type]=q;
    let url=entityPageUrl(type,cursor,q),pending=entityPrefetch.get(url),data=pending?await pending:await api(url);
    entityPrefetch.delete(url);
    if(view!==type)return;
    paintEntityLibrary(type,data,append);
    if(data.has_more&&data.next_cursor)prefetchEntityPage(type,data.next_cursor,q);
  }catch(e){
    if(view!==type)return;
    notify(e.message,'error')
  }
};

searchEntity=async function(type,q){
  $('#entityGrid').innerHTML=empty('Searching TPDB…');
  try{
    let d=await api(`/api/search/${type}?q=${encodeURIComponent(q)}`);
    if(view!==type)return;
    let rows=d.items||d;
    if(type==='scenes'){
      $('#entityGrid').innerHTML=sceneTable(rows,false);
      bindSceneTableActions($('#entityGrid'),false);
      return
    }
    $('#entityGrid').innerHTML=rows.length?rows.map(x=>entityCard(type,x,false)).join(''):empty('No TPDB results found.');
    bindEntityActions(type,false)
  }catch(e){
    if(view!==type)return;
    $('#entityGrid').innerHTML=empty(e.message)
  }
};
