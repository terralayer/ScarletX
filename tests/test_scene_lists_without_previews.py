import subprocess


def test_scene_lists_do_not_request_preview_images_and_keep_actions():
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const app=fs.readFileSync('frontend/app.js','utf8'),ui=fs.readFileSync('frontend/ui_overrides.js','utf8');
const section=(text,start,end)=>text.slice(text.indexOf(start),text.indexOf(end));
const ctx={esc:String,fmtDate:String,bytes:String,durationText:String,
  empty:s=>s,studioLink:()=>'<button>Studio</button>',performerLinks:()=>'<button>Performer</button>',dashboardStudioName:()=> 'Studio',sceneImage:()=> 'preview.jpg'};
vm.createContext(ctx);
vm.runInContext(section(app,'function sceneRowsHtml','function bindSceneTableActions')+
  section(app,'function dashboardRecentRows','function dashboardUpcomingRows')+
  section(app,'function sceneProfileList','function numericPart')+
  section(ui,'function mediaFileRowsHtml','function mediaFilesHtml'),ctx);
const row={id:7,tpdb_id:'scene',title:'Example Scene',release_date:'2026-09-01',image_url:'preview.jpg',monitored:true,media_id:11};
const outputs=[ctx.sceneTable([row],true),ctx.sceneTable([row],false),ctx.sceneProfileList([row]),ctx.dashboardRecentRows([row]),ctx.mediaFileRowsHtml([{id:11,scene_id:7,scene_title:'Example Scene',size_bytes:123}])];
for(const html of outputs){
  assert(!html.includes('<img'),'list rows must not emit preview image elements');
  assert(!html.includes('/api/artwork/scenes/'),'list rows must not request scene artwork');
  assert(html.includes('Example Scene'),'scene titles remain');
}
assert(outputs[0].includes('data-scene-detail'));
assert(outputs[0].includes('data-play-scene="11"'));
assert(outputs[2].includes('2026'));
assert(outputs[3].includes('data-dashboard-scene="7"'));
assert(outputs[4].includes('data-play-media="11"'));
"""
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_profile_scene_rows_show_both_monitoring_states_and_keep_download_status():
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const app=fs.readFileSync('frontend/app.js','utf8');
const ctx={esc:String,fmtDate:String,empty:String,studioLink:()=>'',performerLinks:()=>''};
vm.createContext(ctx);
vm.runInContext(app.slice(app.indexOf('function sceneRowsHtml'),app.indexOf('function bindSceneTableActions'))+
  app.slice(app.indexOf('function sceneProfileList'),app.indexOf('function numericPart')),ctx);
const rows=[
  {id:'unmonitored',local_id:1,title:'Unmonitored Scene',monitored:false,download_status:'Available',release_date:'2026-01-01'},
  {id:'monitored',local_id:2,title:'Monitored Scene',monitored:true,download_status:'Monitored',release_date:'2025-01-01'},
  {id:'downloaded',local_id:3,title:'Downloaded Scene',monitored:false,media_id:11,download_status:'Downloaded'},
];
const html=ctx.sceneProfileList(rows);
for(const row of rows)assert(html.includes(row.title),'every scene must remain visible');
assert(html.includes('>Not monitored</span>'),'unmonitored scenes need an explicit status');
assert(html.includes('>Monitored</span>'));
assert(html.includes('>Downloaded</span>'));
assert(html.includes('data-play-scene="11"'));
assert(ctx.sceneRowsHtml([rows[0]],false).includes('data-monitor-scene'));
assert(!ctx.sceneRowsHtml([rows[1]],false).includes('data-monitor-scene'),'already monitored scenes must not offer Monitor');
assert(html.indexOf('2026')<html.indexOf('2025'));
"""
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
