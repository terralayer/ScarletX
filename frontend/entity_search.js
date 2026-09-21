// Explicit local-first discovery. Provider result pages are persisted by the API.
const entitySearchState={};
function entitySearchPager(result){
  const pages=Math.max(1,Math.ceil(result.total/result.per_page)),page=result.page;
  if(pages<=1)return '';
  const numbers=Array.from({length:pages},(_,i)=>i+1).filter(n=>pages<=7||n===1||n===pages||Math.abs(n-page)<=1);
  return `<div class="pagination-bar entity-pagination"><button class="btn small" data-search-page="${page-1}" ${page<=1?'disabled':''}>Previous</button>${numbers.map(n=>`<button class="btn small" data-search-page="${n}" ${n===page?'disabled':''}>${n}</button>`).join('')}<button class="btn small" data-search-page="${page+1}" ${page>=pages?'disabled':''}>Next</button></div>`;
}
function bindEntitySearch(type,state){
  const grid=$('#entityGrid'),top=$('#entityPaginationTop'),notice=$('#entityNotice');
  const buttons=[...(top?.querySelectorAll('[data-search-page]')||[]),...(grid?.querySelectorAll('[data-search-page]')||[])];
  buttons.forEach(button=>button.onclick=()=>{
    if(!button.disabled)return searchEntity(type,state.query,{source:state.source,page:Number(button.dataset.searchPage)});
  });
  const more=notice?.querySelector('[data-search-online]');
  if(more)more.onclick=()=>searchEntity(type,state.query,{source:'online',page:1});
}
async function searchEntity(type,query,options={}){
  const grid=$('#entityGrid'),top=$('#entityPaginationTop'),notice=$('#entityNotice');
  if(!grid)return false;
  const source=options.source||'local',page=options.page||1,generation=nextEntityRequest(type),prior=entitySearchState[type];
  const current=()=>view===type&&entityRequestCurrent(type,generation)&&$('#entityGrid')===grid;
  const oldNotice=notice?.innerHTML||'',oldTop=top?.innerHTML||'',buttons=[...(top?.querySelectorAll('[data-search-page]')||[]),...grid.querySelectorAll('[data-search-page]')],disabled=buttons.map(button=>button.disabled);
  buttons.forEach(b=>b.disabled=true);
  if(!prior||prior.query!==query||!options.source)grid.innerHTML=empty('Searching saved library…');
  if(notice)notice.innerHTML=`<div class="notice info" role="status">${source==='online'?'Checking saved provider results and finding more online…':'Searching saved library…'}</div>`;
  try{
    const url=`/api/search/${type}?q=${encodeURIComponent(query)}&page=${page}`+(type==='scenes'?'':`&source=${source}`);
    const response=await api(url);
    if(!current())return false;
    const result=Array.isArray(response)?{items:response,total:response.length,page:1,per_page:24}:response;
    if(type!=='scenes'&&source==='local'&&page===1&&!(result.items||[]).length)return searchEntity(type,query,{source:'online',page:1});
    const rows=result.items||[],state={query,source,page:result.page||page};
    if(type==='scenes'){grid.innerHTML=sceneTable(rows,false);bindSceneTableActions(grid,false)}
    else{grid.innerHTML=rows.length?rows.map(row=>entityCard(type,row,false)).join(''):empty(source==='local'?'No saved matches. Use Find more online to discover more.':'No provider results found.');bindEntityActions(type,false)}
    const pager=entitySearchPager({...result,page:state.page,per_page:result.per_page||24});
    if(top)top.innerHTML=pager;
    grid.insertAdjacentHTML('beforeend',pager);
    entitySearchState[type]=state;
    if(notice)notice.innerHTML=`<div class="search-summary" role="status"><span>${Number(result.total||0).toLocaleString()} ${source==='online'?'provider':'saved'} results${source==='online'?' · fetched results saved locally':''}</span>${type!=='scenes'&&source==='local'?'<button class="btn small" data-search-online>Find more online</button>':''}</div>`;
    bindEntitySearch(type,state);
    if(options.page&&prior&&prior.query===query&&(prior.page!==state.page||prior.source!==source))$('#app')?.scrollIntoView({block:'start',behavior:'auto'});
    return true;
  }catch(error){
    if(!current())return false;
    if(top)top.innerHTML=oldTop;
    if(notice)notice.innerHTML=oldNotice||'<button class="btn small" data-search-online>Find more online</button>';
    if(!prior||prior.query!==query)grid.innerHTML=empty('Search could not load. Try again.');
    if(prior&&prior.query===query)buttons.forEach((button,index)=>button.disabled=disabled[index]);
    bindEntitySearch(type,prior||{query,source:'local',page:1});notify(error.message,'error');
    return false;
  }
}
