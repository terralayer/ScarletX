from __future__ import annotations
import shutil
from pathlib import Path
from sqlalchemy import exists, select
from .library_management import QUALITY_ORDER,default_quality_profile,detect_quality,ensure_library_config
from .models import LibraryItemConfig,MediaFile,QualityProfile,RootFolder,Scene

def _profile_for(db,scene):
    cfg=ensure_library_config(db,scene);return db.get(QualityProfile,cfg.quality_profile_id) if cfg.quality_profile_id else default_quality_profile(db,"scene")
def missing_items(db,content_type=None,limit=500):
    scenes=db.scalars(
        select(Scene).where(
            Scene.monitored.is_(True),Scene.content_type=="scene",
            ~exists(select(MediaFile.id).where(MediaFile.scene_id==Scene.id)),
        ).order_by(Scene.release_date,Scene.title).limit(limit)
    ).all()
    return [{"kind":"scene","library_item_id":scene.id,"title":scene.title,"release_date":scene.release_date,"metadata_id":scene.tpdb_id} for scene in scenes]
def cutoff_unmet(db,content_type=None,limit=500):
    scenes=db.scalars(select(Scene).where(Scene.monitored.is_(True),Scene.content_type=="scene")).all()
    if not scenes:return []
    configs={item.scene_id:item for item in db.scalars(
        select(LibraryItemConfig).join(Scene,Scene.id==LibraryItemConfig.scene_id).where(
            Scene.monitored.is_(True),Scene.content_type=="scene"
        )
    ).all()}
    profiles={item.id:item for item in db.scalars(select(QualityProfile)).all()}
    default=default_quality_profile(db,"scene")
    files_by_scene={}
    for media in db.scalars(
        select(MediaFile).join(Scene,Scene.id==MediaFile.scene_id).where(
            Scene.monitored.is_(True),Scene.content_type=="scene"
        )
    ).all():
        files_by_scene.setdefault(media.scene_id,[]).append(media)
    rows=[]
    for scene in scenes:
        config=configs.get(scene.id)
        profile=profiles.get(config.quality_profile_id) if config and config.quality_profile_id else default
        if not profile:continue
        files=files_by_scene.get(scene.id,[])
        if not files:continue
        best=max(files,key=lambda x:QUALITY_ORDER.get(detect_quality(x.quality or x.release_title or "").resolution,0))
        current=detect_quality(best.quality or best.release_title or "").resolution
        if QUALITY_ORDER.get(current,0)<QUALITY_ORDER.get(profile.cutoff_quality.casefold(),0):
            rows.append({"kind":"scene","library_item_id":scene.id,"title":scene.title,"current_quality":current,"cutoff":profile.cutoff_quality})
        if len(rows)>=limit:break
    return rows
def calendar_items(db,start,end,limit=500):
    rows=[]
    stmt = select(Scene).where(
        Scene.content_type == "scene", Scene.monitored.is_(True),
        Scene.release_date >= start, Scene.release_date <= end,
    ).order_by(Scene.release_date, Scene.title).limit(limit)
    for s in db.scalars(stmt).all():
        rows.append({"date":s.release_date,"kind":"scene","library_item_id":s.id,"title":s.title,"monitored":s.monitored})
    return rows
def disk_space(db):
    rows=[]
    for root in db.scalars(select(RootFolder).where(RootFolder.content_type=="scene").order_by(RootFolder.name)).all():
        path=Path(root.path).expanduser()
        if not path.exists(): rows.append({"root_folder_id":root.id,"name":root.name,"content_type":"scene","path":root.path,"exists":False});continue
        try:
            u=shutil.disk_usage(path);rows.append({"root_folder_id":root.id,"name":root.name,"content_type":"scene","path":root.path,"exists":True,"total_bytes":u.total,"used_bytes":u.used,"free_bytes":u.free,"free_percent":round((u.free/u.total*100) if u.total else 0,1)})
        except OSError as exc:rows.append({"root_folder_id":root.id,"name":root.name,"content_type":"scene","path":root.path,"exists":True,"error":str(exc)})
    return rows
