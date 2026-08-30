from __future__ import annotations
import asyncio
from datetime import UTC,datetime
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from .automation import _current_scene_file,choose_best_release,grab_specific_release,title_match_bonus
from .library_management import default_quality_profile,ensure_library_config
from .models import IndexerFeedItem,LibraryItemConfig,MediaFile,QualityProfile,Scene
from .newznab import NewznabClient,NewznabError
async def _fetch(i,limit):
    async with NewznabClient(i) as c:return await c.rss(limit,content_type="scene")
def _exists(db,r):return db.scalar(select(IndexerFeedItem.id).where(IndexerFeedItem.indexer==r.indexer,IndexerFeedItem.guid==r.guid).limit(1)) is not None
def _record(db,r,action,scene_id=None,reason=None):
    db.add(IndexerFeedItem(indexer=r.indexer,guid=r.guid,title=r.title,published_at=r.published_at,action=action,scene_id=scene_id,reason=(reason or "")[:1000] or None))
    try:db.commit()
    except IntegrityError:db.rollback()
def _profile(db,s):
    cfg=ensure_library_config(db,s);return db.get(QualityProfile,cfg.quality_profile_id) if cfg.quality_profile_id else default_quality_profile(db,"scene")
def _match(db,r,context=None):
    ranked=[]
    if context is None:
        scenes=db.scalars(select(Scene).where(Scene.content_type=="scene",Scene.monitored.is_(True)).options(selectinload(Scene.studio))).all()
        profiles={s.id:_profile(db,s) for s in scenes}
        current={s.id:_current_scene_file(db,s.id) for s in scenes}
    else:
        scenes,profiles,current=context
    for s in scenes:
        bonus=title_match_bonus(s,r.title)
        if bonus is None:continue
        p=profiles.get(s.id)
        if not p:continue
        chosen=choose_best_release(s,[r],p,current.get(s.id),db=db)
        if chosen:ranked.append((chosen[0]+bonus,s,chosen))
    return max(ranked,key=lambda x:x[0]) if ranked else None

def _match_context(db):
    scenes=db.scalars(select(Scene).where(Scene.content_type=="scene",Scene.monitored.is_(True)).options(selectinload(Scene.studio))).all()
    if not scenes:return ([],{}, {})
    ids=[scene.id for scene in scenes]
    configs={item.scene_id:item for item in db.scalars(select(LibraryItemConfig).where(LibraryItemConfig.scene_id.in_(ids))).all()}
    profiles_by_id={item.id:item for item in db.scalars(select(QualityProfile)).all()}
    default=default_quality_profile(db,"scene")
    profiles={scene.id:(profiles_by_id.get(configs[scene.id].quality_profile_id) if scene.id in configs and configs[scene.id].quality_profile_id else default) for scene in scenes}
    current={}
    for media in db.scalars(select(MediaFile).where(MediaFile.scene_id.in_(ids)).order_by(MediaFile.imported_at.desc())).all():
        current.setdefault(media.scene_id,media)
    return scenes,profiles,current
async def rss_sync_cycle(session_factory,settings,*,force=False):
    if not settings.rss_sync_enabled and not force:return {"enabled":False,"fetched":0,"new":0,"matched":0,"queued":0,"errors":{}}
    idx=[i for i in settings.newznab_indexers() if i.enabled and i.rss_enabled]
    if not idx:return {"enabled":settings.rss_sync_enabled,"fetched":0,"new":0,"matched":0,"queued":0,"errors":{"ScarletX":"No RSS-enabled Newznab indexers"}}
    responses=await asyncio.gather(*(_fetch(i,settings.rss_max_releases_per_indexer) for i in idx),return_exceptions=True);releases=[];errors={}
    for i,r in zip(idx,responses,strict=True):
        if isinstance(r,Exception):errors[i.name]=str(r) if isinstance(r,NewznabError) else "RSS fetch failed"
        else:releases.extend(r)
    releases.sort(key=lambda x:x.published_at or datetime.min.replace(tzinfo=UTC),reverse=True);new=matched=queued=0;results=[]
    with session_factory() as context_db:match_context=_match_context(context_db)
    for r in releases:
        with session_factory() as db:
            if _exists(db,r):continue
            new+=1;m=_match(db,r,match_context)
            if not m:_record(db,r,"ignored",reason="No monitored scene matched");continue
            matched+=1;_,scene,chosen=m;sid=scene.id;query=scene.title
        if queued>=settings.rss_max_grabs_per_cycle:
            with session_factory() as db:_record(db,r,"matched_not_grabbed",sid,"RSS grab limit reached")
            continue
        result=await grab_specific_release(session_factory,settings,scene_id=sid,release=r,query=query,score=chosen[0])
        with session_factory() as db:_record(db,r,"grabbed" if result.status=="queued" else result.status,sid,result.error)
        results.append(result.as_dict());queued+=1 if result.status=="queued" else 0
    return {"enabled":settings.rss_sync_enabled,"fetched":len(releases),"new":new,"matched":matched,"queued":queued,"errors":errors,"results":results}
