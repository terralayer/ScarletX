let navigationGeneration=0;
function nextNavigationGeneration(){navigationGeneration+=1;return navigationGeneration}
function navigationGenerationCurrent(generation){return generation===navigationGeneration}

loadEntityLibrary=async function(type,cursor=null,append=false,q=null){
  const generation=nextNavigationGeneration();
  const grid=$('#entityGrid');
  try{
    if(q===null)q=entityLibraryQuery[type]||'';
    if(!append)entityLibraryQuery[type]=q;
    let url=entityPageUrl(type,cursor,q),pending=entityPrefetch.get(url),data=pending?await pending:await api(url);
    entityPrefetch.delete(url);
    if(view!==type||!navigationGenerationCurrent(generation)||$('#entityGrid')!==grid)return;
    paintEntityLibrary(type,data,append);
    if(data.has_more&&data.next_cursor)prefetchEntityPage(type,data.next_cursor,q);
  }catch(e){
    if(view!==type||!navigationGenerationCurrent(generation)||$('#entityGrid')!==grid)return;
    notify(e.message,'error')
  }
};

searchEntity=async function(type,q){
  const generation=nextNavigationGeneration();
  const grid=$('#entityGrid');
  if(!grid)return;
  grid.innerHTML=empty('Searching TPDB…');
  try{
    let d=await api(`/api/search/${type}?q=${encodeURIComponent(q)}`);
    if(view!==type||!navigationGenerationCurrent(generation)||$('#entityGrid')!==grid)return;
    let rows=d.items||d;
    if(type==='scenes'){
      grid.innerHTML=sceneTable(rows,false);
      bindSceneTableActions(grid,false);
      return
    }
    grid.innerHTML=rows.length?rows.map(x=>entityCard(type,x,false)).join(''):empty('No TPDB results found.');
    bindEntityActions(type,false)
  }catch(e){
    if(view!==type||!navigationGenerationCurrent(generation)||$('#entityGrid')!==grid)return;
    grid.innerHTML=empty(e.message)
  }
};
