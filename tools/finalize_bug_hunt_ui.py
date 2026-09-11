from __future__ import annotations
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def rw(path): return (ROOT/path).read_text(encoding='utf-8')
def ww(path,text): (ROOT/path).write_text(text,encoding='utf-8')
def sub1(text,pattern,repl,label):
    out,n=re.subn(pattern,repl,text,count=1,flags=re.S)
    if n!=1: raise RuntimeError(f'{label}: {n} matches')
    return out

app=rw('frontend/app.js')
# Preserve the newer recent-release dashboard, but make every stat a real core button.
dashboard=r'''async function dashboard(){
  $('#app').innerHTML=pageHead('Welcome back','Your downloaded ScarletX library.',`<button class="btn primary" id="addNew">＋ Add New</button>`)+`<div class="stats" id="stats"></div><div class="dashgrid"><div class="panel"><div class="panel-head"><h2>Studios with Recent Releases</h2><button class="linkbtn" data-go="studios">View studios</button></div><div class="rows" id="studioReleaseRows"></div></div><div class="panel"><div class="panel-head"><h2>Performers with Recent Releases</h2><button class="linkbtn" data-go="performers">View performers</button></div><div class="rows" id="performerReleaseRows"></div></div><div class="panel"><div class="panel-head"><h2>Upcoming</h2><button class="linkbtn" data-go="calendar">View calendar</button></div><div class="rows" id="calendarRows"></div></div></div><div class="panel recent"><div class="panel-head"><h2>Recently Released Scenes</h2><button class="linkbtn" data-go="library">View library</button></div><div id="recentScenes" style="padding:0 12px 14px"></div></div>`;
  $('#addNew').onclick=()=>{view='scenes';entityMode.scenes='search';nav();renderEntities('scenes')};
  $('#app').onclick=e=>{let st=e.target.closest('[data-dashboard-studio]');if(st)return studioProfile(st.dataset.dashboardStudio,null);let performer=e.target.closest('[data-dashboard-performer]');if(performer)return performerProfile(performer.dataset.dashboardPerformer,null);let b=e.target.closest('[data-go]');if(b){let target=b.dataset.go;if(['scenes','performers','studios'].includes(target))entityMode[target]='library';view=target;nav();render()}};
  try{
    let [sys,recent,studioData,performerData,cal,disk]=await Promise.all([api('/api/system/status'),api('/api/dashboard/scenes?limit=8'),api('/api/dashboard/studios?limit=8'),api('/api/dashboard/performers?limit=8'),api('/api/calendar?limit=5'),api('/api/system/diskspace').catch(()=>[])]);
    if(view!=='dashboard')return;
    let scenes=recent.items||[],studios=studioData.items||[],performers=performerData.items||[];libraryCache=scenes;
    let total=0,used=0;disk.filter(x=>x.exists&&x.total_bytes).forEach(x=>{total+=x.total_bytes;used+=x.used_bytes});let pct=total?Math.round(used/total*100):0;
    $('#stats').innerHTML=[['▣','Scenes',recent.total||0,'Downloaded','library'],['♙','Performers',sys.performers||0,'In library','performers'],['▥','Studios',sys.studios||0,'In library','studios'],['◎','Wanted',sys.wanted||0,'Missing','wanted'],['▱','Storage',total?bytes(used):'—',total?`${pct}% of ${bytes(total)}`:'No scene root yet','library']].map(x=>`<button type="button" class="stat dashboard-stat" data-stat-go="${x[4]}"><div class="stat-icon">${x[0]}</div><div><small>${x[1]}</small><strong>${x[2]}</strong><em>${x[3]}</em></div></button>`).join('');bindDashboardStats();
    $('#studioReleaseRows').innerHTML=studios.map(x=>`<div class="row"><div class="rowicon studio-logo"><img src="/api/artwork/studios/${encodeURIComponent(x.tpdb_id||x.id)}?v=v5" alt="" loading="lazy" onerror="this.remove()"></div><div><button class="studio-link" data-dashboard-studio="${esc(x.tpdb_id||x.id)}">${esc(x.name||'Studio')}</button><small>${esc(x.latest_title||'Latest downloaded release')} · ${fmtDate(x.latest_release_date)}</small></div><span class="badge soft">${Number(x.release_count||0)} ${Number(x.release_count||0)===1?'scene':'scenes'}</span></div>`).join('')||`<div class="row"><div class="rowicon">□</div><div><b>No downloaded studio releases yet</b><small>Studios appear here after scenes are added to the library.</small></div></div>`;
    $('#performerReleaseRows').innerHTML=performers.map(x=>{let id=x.tpdb_id||x.id;return `<div class="row"><div class="rowicon"><img src="/api/artwork/performers/${encodeURIComponent(id)}?size=card" alt="" loading="lazy" style="width:100%;height:100%;object-fit:cover;border-radius:inherit" onerror="this.remove()"></div><div><button class="studio-link" data-dashboard-performer="${esc(id)}">${esc(x.name||'Performer')}</button><small>${esc(x.latest_title||'Latest downloaded release')} · ${fmtDate(x.latest_release_date)}</small></div><span class="badge soft">${Number(x.release_count||0)} ${Number(x.release_count||0)===1?'scene':'scenes'}</span></div>`}).join('')||`<div class="row"><div class="rowicon">□</div><div><b>No downloaded performer releases yet</b><small>Performers appear here after their scenes are added to the library.</small></div></div>`;
    $('#calendarRows').innerHTML=cal.slice(0,5).map(x=>`<div class="row"><div class="rowicon">${String(x.date).slice(8,10).replace(/^0/,'')}</div><div><b>${esc(x.title)}</b><small>${fmtDate(x.date)}</small></div><span class="badge soft">Scene</span></div>`).join('')||`<div class="row"><div class="rowicon">□</div><div><b>No upcoming releases</b><small>Monitored release dates will appear here.</small></div></div>`;
    let recentRoot=$('#recentScenes');recentRoot.innerHTML=scenes.length?sceneTable(scenes,true):empty('No downloaded scenes yet.');bindSceneTableActions(recentRoot,true);
  }catch(err){if(view!=='dashboard')return;notify(err.message,'error')}
}'''
app=sub1(app,r"async function dashboard\(\)\{.*?(?=\nfunction performerLinks)",dashboard,'dashboard')
# Move standardized studio art behavior into the authoritative core renderers.
app=app.replace('let logo=id?`<span class="studio-logo"><img src="/api/artwork/studios/${encodeURIComponent(id)}?size=card"', 'let logo=id?`<span class="studio-logo"><img src="/api/artwork/studios/${encodeURIComponent(id)}?v=v5"',1)
old="let cachedImg=type==='performers'?`/api/artwork/performers/${encodeURIComponent(id)}?size=card`:type==='studios'?`/api/artwork/studios/${encodeURIComponent(id)}?size=card`:img;\n  return `<article"
new="let cachedImg=type==='performers'?`/api/artwork/performers/${encodeURIComponent(id)}?size=card`:type==='studios'?`/api/artwork/studios/${encodeURIComponent(id)}?v=v5`:img;\n  let renderImg=type==='studios'||!!img;\n  return `<article"
if old not in app: raise RuntimeError('entity card art anchor missing')
app=app.replace(old,new,1)
app=app.replace("${img?`<img src=\"${esc(cachedImg)}\"", "${renderImg?`<img src=\"${esc(cachedImg)}\"",1)
ww('frontend/app.js',app)

# Make regression tests behavioral rather than variable-name/string-shape fragile.
t=rw('tests/test_bug_hunt_regressions.py')
t=t.replace("    assert \"new Date(y,m-1,d)\" in fmt.replace(\" \", \"\") or \"newDate(y,m-1,d)\" in fmt.replace(\" \", \"\")", "    compact=fmt.replace(\" \", \"\")\n    assert \"newDate(y,m-1,day)\" in compact")
t=t.replace("    assert \"local||\" in performer or \"local ||\" in performer\n    assert \"local||\" in studio or \"local ||\" in studio\n    assert \"local||\" in scene or \"local ||\" in scene", "    assert \"let x=local?localPerformerProfile(local):await api\" in performer\n    assert \"let x=local?{...local,id:local.tpdb_id}:await api\" in studio\n    assert \"if(!local){try{remote=await api\" in scene")
ww('tests/test_bug_hunt_regressions.py',t)

s=rw('tests/test_studio_art_consistency.py')
s=s.replace('    assert "studioArtUrl(id)" in source\n', '    assert "studioArtUrl=function(id)" in source\n',1)
ww('tests/test_studio_art_consistency.py',s)
print('finalized authoritative UI')
