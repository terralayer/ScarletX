// One transition owner for all paged lists. Loaders commit only current responses.
const listPageTransitions=new WeakSet();
async function changeListPage({host,page,getPage,setPage,load,current=()=>host?.isConnected,scrollTarget=host}){
  if(!host||listPageTransitions.has(host)||!Number.isInteger(page)||page<1||page===getPage())return false;
  const previous=getPage(),buttons=[...host.querySelectorAll('.pagination-bar button,.pager button')],disabled=buttons.map(b=>b.disabled);
  listPageTransitions.add(host);buttons.forEach(b=>b.disabled=true);setPage(page);
  try{
    const loaded=await load();
    if(!current())return false;
    if(loaded!==true){if(getPage()===page)setPage(previous);return false}
    scrollTarget?.scrollIntoView({block:'start',behavior:'auto'});
    return true;
  }catch(error){
    if(current()){if(getPage()===page)setPage(previous);notify(error.message,'error')}
    return false;
  }finally{
    listPageTransitions.delete(host);
    buttons.forEach((button,index)=>{if(button.isConnected!==false)button.disabled=disabled[index]});
  }
}
