from __future__ import annotations
import asyncio,re
from dataclasses import dataclass
from datetime import UTC,datetime
from sqlalchemy import select
from sqlalchemy.orm import Session,sessionmaker
from .config import Settings
from .library_management import QUALITY_ORDER,default_quality_profile,detect_quality,ensure_library_config,score_release
from .models import History,MediaFile,QualityProfile,ReleaseBlocklist,Scene,TrackedDownload,TrackedDownloadMeta,utcnow
from .newznab import NewznabClient,NewznabError,NewznabRelease
from .notifications import emit_webhooks
from .release_profiles import apply_release_profiles
from .download_clients import DownloadClientError, submit_release
ACTIVE_DOWNLOAD_STATES={"queued","downloading","paused","postprocessing","import_pending"}
@dataclass(frozen=True)
class GrabResult:
    status:str;scene_id:int;query:str;title:str|None=None;indexer:str|None=None;quality:str|None=None;nzo_ids:tuple[str,...]=();error:str|None=None;download_client:str|None=None;score:int|None=None
    def as_dict(self):return {"status":self.status,"scene_id":self.scene_id,"query":self.query,"title":self.title,"indexer":self.indexer,"quality":self.quality,"nzo_ids":list(self.nzo_ids),"error":self.error,"download_client":self.download_client,"score":self.score}
def build_search_query(scene):
    bits=[scene.title]
    if scene.studio and scene.studio.name:bits.insert(0,scene.studio.name)
    return " ".join(x.strip() for x in bits if x and x.strip())
def _title_tokens(v):return {x for x in re.findall(r"[a-z0-9]+",v.casefold()) if len(x)>=3 and x not in {"the","and","for","with","from","this","that"}}
def title_match_bonus(scene,release_title):
    expected=_title_tokens(scene.title)
    if not expected:return 0
    release=_title_tokens(release_title);ratio=len(expected&release)/len(expected)
    return None if ratio<.45 else int(ratio*300)
NON_STUDIO={"onlyfans","manyvids","fansly","loyalfans","patreon","fancentro","justforfans","fanvue","clips4sale","iwantclips","unfiltrd","amateur","homemade","leaked","leak","megapack","mega","compilation","analvids","anal vids"}
GENERIC={"studio","studios","network","networks","productions","production","entertainment","media","official","com","xxx"}
def adult_studio_release_allowed(scene,release_title):
    normalized=set(re.findall(r"[a-z0-9]+",release_title.casefold()));compact=re.sub(r"[^a-z0-9]","",release_title.casefold())
    if any(t in normalized or (len(re.sub(r"[^a-z0-9]","",t))>=6 and re.sub(r"[^a-z0-9]","",t) in compact) for t in NON_STUDIO):return False
    if not scene.studio or not scene.studio.name:return False
    tokens=_title_tokens(scene.studio.name)-GENERIC
    if not tokens:tokens=set(re.findall(r"[a-z0-9]+",scene.studio.name.casefold()))-GENERIC
    if tokens&normalized:return True
    sc=re.sub(r"[^a-z0-9]","",scene.studio.name.casefold());return len(sc)>=4 and sc in compact
async def search_all_indexers(settings,query,limit=100,content_type="scene"):
    indexers=[x for x in settings.newznab_indexers() if x.enabled]
    if not indexers:return [],{"ScarletX":"No enabled Newznab indexers are configured"}
    async def one(i):
        async with NewznabClient(i) as c:return await c.search(query,limit,content_type="scene")
    responses=await asyncio.gather(*(one(i) for i in indexers),return_exceptions=True);out=[];errors={};priority={i.name:i.priority for i in indexers}
    for i,r in zip(indexers,responses,strict=True):
        if isinstance(r,Exception):errors[i.name]=str(r) if isinstance(r,NewznabError) else "Search failed"
        else:out.extend(r)
    out.sort(key=lambda x:priority.get(x.indexer,25));return out,errors
def _blocked(db,release):
    now=utcnow()
    for row in db.scalars(select(ReleaseBlocklist).where((ReleaseBlocklist.indexer==release.indexer)|(ReleaseBlocklist.indexer.is_(None)))).all():
        if row.expires_at and row.expires_at<now:continue
        if row.guid and row.guid==release.guid:return True
        if row.release_title.casefold()==release.title.casefold():return True
    return False
def choose_best_release(scene,releases,profile,current=None,*,db=None):
    current_resolution=detect_quality(current.quality).resolution if current and current.quality else "unknown";ranked=[]
    for release in releases:
        if (db is not None and _blocked(db,release)) or not adult_studio_release_allowed(scene,release.title):continue
        qs=score_release(release.title,release.size,profile);bonus=title_match_bonus(scene,release.title)
        if qs is None or bonus is None:continue
        extra=0
        if db is not None:
            applied=apply_release_profiles(db,title=release.title,content_type="scene",indexer=release.indexer)
            if applied is None:continue
            extra=applied[0]
        if current:
            if not profile.upgrades_allowed or QUALITY_ORDER.get(qs.quality.resolution,0)<=QUALITY_ORDER.get(current_resolution,0):continue
        ranked.append((qs.score+bonus+extra,release,qs.quality.label))
    if not ranked:return None
    ranked.sort(key=lambda x:(x[0],x[1].published_at or datetime.min.replace(tzinfo=UTC)),reverse=True);return ranked[0]
def _current_scene_file(db,scene_id):return db.scalar(select(MediaFile).where(MediaFile.scene_id==scene_id).order_by(MediaFile.imported_at.desc()).limit(1))
async def _submit_release(session_factory,settings,release,name=None):
    try:
        submitted=await submit_release(settings,release,session_factory=session_factory,name=name or release.title)
    except DownloadClientError as exc:raise RuntimeError(str(exc)) from exc
    return submitted
def _track(db,ids,release,query,scene,score,download_client):
    for external_id in ids:
        tracked=db.scalar(select(TrackedDownload).where(TrackedDownload.nzo_id==external_id))
        if tracked is None:
            tracked=TrackedDownload(nzo_id=external_id,release_title=release.title,indexer=release.indexer,query=query,scene_tpdb_id=scene.tpdb_id,scene_title=scene.title,scene_id=scene.id,status="queued");db.add(tracked);db.flush()
        meta=db.get(TrackedDownloadMeta,tracked.id)
        if meta is None:meta=TrackedDownloadMeta(tracked_download_id=tracked.id);db.add(meta)
        meta.download_client=download_client;meta.release_guid=release.guid;meta.protocol="usenet";meta.score=score
    db.flush()
async def grab_specific_release(session_factory,settings,*,scene_id,release,query,score=None,**_):
    with session_factory() as db:
        scene=db.get(Scene,scene_id)
        if not scene or scene.content_type!="scene":return GrabResult("not_found",scene_id,query,error="Scene not found")
        if _blocked(db,release):return GrabResult("blocked",scene_id,query,title=scene.title,error="Release is blocklisted")
        if not adult_studio_release_allowed(scene,release.title):return GrabResult("blocked",scene_id,query,title=scene.title,error="Release is not a matching studio release")
        if db.scalar(select(TrackedDownload.id).where(TrackedDownload.scene_id==scene.id,TrackedDownload.status.in_(ACTIVE_DOWNLOAD_STATES)).limit(1)):return GrabResult("already_downloading",scene.id,query,title=scene.title)
        title=scene.title
    try:submitted=await _submit_release(session_factory,settings,release,name=title)
    except RuntimeError as exc:return GrabResult("error",scene_id,query,title=title,error=str(exc))
    ids=submitted.ids;download_client=submitted.client
    client_label="ScarletX Built-In"
    with session_factory() as db:
        scene=db.get(Scene,scene_id);_track(db,ids,release,query,scene,score,download_client);db.add(History(event_type="auto_release_grabbed",scene_id=scene.id,message=f"Sent {release.title} from {release.indexer} to {client_label} for {scene.title}"));db.commit()
    await emit_webhooks(session_factory,"grab",{"scene_id":scene_id,"title":title,"release_title":release.title,"indexer":release.indexer,"download_client":download_client})
    return GrabResult("queued",scene_id,query,title=release.title,indexer=release.indexer,quality=detect_quality(release.title).label,nzo_ids=ids,download_client=download_client,score=score)
async def _search_scene_releases(settings,scene):
    primary=build_search_query(scene);releases,errors=await search_all_indexers(settings,primary)
    fallback=scene.title.strip()
    if fallback and fallback.casefold()!=primary.casefold():
        extra,e2=await search_all_indexers(settings,fallback);merged={(r.indexer,r.guid):r for r in [*releases,*extra]};releases=list(merged.values());errors.update({k:v for k,v in e2.items() if k not in errors})
    return primary,releases,errors
async def search_and_grab_scene(session_factory,scene_id,settings,**_):
    with session_factory() as db:
        scene=db.get(Scene,scene_id)
        if not scene or scene.content_type!="scene":return GrabResult("not_found",scene_id,"",error="Scene not found")
        cfg=ensure_library_config(db,scene);profile=db.get(QualityProfile,cfg.quality_profile_id) if cfg.quality_profile_id else default_quality_profile(db,"scene")
        if not profile:return GrabResult("blocked",scene_id,build_search_query(scene),error="No quality profile is configured")
        if db.scalar(select(TrackedDownload.id).where(TrackedDownload.scene_id==scene.id,TrackedDownload.status.in_(ACTIVE_DOWNLOAD_STATES)).limit(1)):return GrabResult("already_downloading",scene.id,build_search_query(scene),title=scene.title)
        profile_id=profile.id;title=scene.title
    with session_factory() as db:scene=db.get(Scene,scene_id);query,releases,errors=await _search_scene_releases(settings,scene)
    with session_factory() as db:
        scene=db.get(Scene,scene_id);profile=db.get(QualityProfile,profile_id);current=_current_scene_file(db,scene_id);cfg=ensure_library_config(db,scene);cfg.last_search_at=utcnow();chosen=choose_best_release(scene,releases,profile,current,db=db);db.commit()
    if not chosen:return GrabResult("no_match",scene_id,query,title=title,error="; ".join(f"{k}: {v}" for k,v in errors.items()) if errors and not releases else None)
    score,release,quality=chosen;result=await grab_specific_release(session_factory,settings,scene_id=scene_id,release=release,query=query,score=score)
    return GrabResult(**{**result.__dict__,"quality":quality}) if result.status=="queued" else result
async def automatic_search_cycle(session_factory,settings):
    if not settings.automatic_search_enabled:return {"enabled":False,"checked":0,"queued":0,"results":[]}
    if not [x for x in settings.newznab_indexers() if x.enabled]:return {"enabled":True,"checked":0,"queued":0,"results":[],"blocked":"No enabled indexer is configured"}
    with session_factory() as db:
        ids=[]
        for scene in db.scalars(select(Scene).where(Scene.monitored.is_(True),Scene.content_type=="scene").order_by(Scene.imported_at.asc())).all():
            cfg=ensure_library_config(db,scene)
            if not cfg.search_enabled:continue
            if db.scalar(select(TrackedDownload.id).where(TrackedDownload.scene_id==scene.id,TrackedDownload.status.in_(ACTIVE_DOWNLOAD_STATES)).limit(1)):continue
            media=_current_scene_file(db,scene.id);profile=db.get(QualityProfile,cfg.quality_profile_id) if cfg.quality_profile_id else default_quality_profile(db,"scene")
            if media and profile and not profile.upgrades_allowed:continue
            ids.append(scene.id)
            if len(ids)>=settings.automatic_search_batch_size:break
        db.commit()
    results=[]
    for ident in ids:results.append((await search_and_grab_scene(session_factory,ident,settings)).as_dict())
    return {"enabled":True,"checked":len(results),"queued":sum(1 for x in results if x["status"]=="queued"),"results":results}
