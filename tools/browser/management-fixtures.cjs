module.exports = function managementFixture(pathname) {
  if(pathname==='/api/operations/connections')return {steps:[['metadata','TPDB'],['indexers','Indexers'],['downloads','Usenet providers']].map(([id,title])=>({id,title,configured:true,revision:'fixture-1'}))};
  if(pathname.endsWith('/test'))return {ok:true,revision:'fixture-1'};
  if(pathname==='/api/operations/backup-reminder')return {state:'healthy',message:'Your latest backup is up to date.',enabled:true,last_success_at:'2026-09-17T10:00:00Z',next_due_at:'2026-09-18T10:00:00Z'};
  if(pathname==='/api/operations/download-schedule')return {rule:{enabled:false,start:'22:00',end:'07:00',timezone:'UTC',mode:'pause',speed_limit_mb_s:5},state:{active:false,paused:false}};
  if(pathname==='/api/operations/storage')return {note:'Filesystem usage includes other folders. Shared filesystems must not be added together.',items:['Active downloads','Completed downloads','Backups','Artwork cache','Media: Scenes'].map((name,i)=>({name,path:['/downloads/incomplete','/downloads/complete','/backups','/config/cache/tpdb/images','/media/scenes'][i],total_bytes:4*1024**4,used_bytes:1024**4,free_bytes:3*1024**4,folder:{bytes:(i+1)*1024**3,complete:i!==4,error:i===4?'Partial count: scan limit reached':null}}))};
  if(pathname==='/api/operations/cleanup')return {items:[{id:1,title:'Autumn Light',path:'/media/Example Studio/Autumn Light.mp4'}],has_more:false,note:'Preview only. Potential duplicates share a partial fingerprint; verify contents before taking action.'};
  throw new Error('Unknown operations fixture '+pathname);
};
