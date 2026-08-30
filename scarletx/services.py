from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from .models import AppSetting, BackgroundJob, History, Performer, Scene, Studio, Tag, scene_performer
from .schemas import RemotePerson, RemoteScene, RemoteStudio
from .studio_policy import is_allowed_remote_scene


def upsert_scene(db: Session, remote: RemoteScene, monitored: bool = True, content_type: str = "scene") -> Scene:
    if content_type == "scene" and not is_allowed_remote_scene(remote):
        raise ValueError("ScarletX only allows scenes from production studios/sites")
    scene = db.scalar(select(Scene).where(Scene.tpdb_id == remote.id).options(selectinload(Scene.performers), selectinload(Scene.tags)))
    created = scene is None
    if scene is None:
        scene = Scene(tpdb_id=remote.id, title=remote.title, monitored=monitored, content_type=content_type)
        db.add(scene)
    scene.title, scene.description, scene.release_date = remote.title, remote.description, remote.release_date
    scene.content_type = content_type
    scene.duration, scene.source_url = remote.duration, remote.source_url
    scene.image_url, scene.back_image_url, scene.poster_url = remote.image_url, remote.back_image_url, remote.poster_url
    scene.monitored = monitored if created else scene.monitored
    if remote.studio:
        studio = db.scalar(select(Studio).where(Studio.tpdb_id == remote.studio.id))
        if not studio:
            studio = Studio(tpdb_id=remote.studio.id, name=remote.studio.name); db.add(studio)
        studio.name, studio.url, studio.logo_url = remote.studio.name, remote.studio.url, remote.studio.logo_url
        studio.poster_url, studio.description = remote.studio.poster_url, remote.studio.description
        # Adult scene ingestion lists the credited studio in Adult > Studios, but
        # monitoring is an explicit user action. Never change an existing monitor flag
        # just because another scene credits the studio.
        if content_type == "scene":
            studio.is_library = True
        scene.studio = studio
    scene.performers = []
    for item in remote.performers:
        obj = db.scalar(select(Performer).where(Performer.tpdb_id == item.id))
        if not obj: obj = Performer(tpdb_id=item.id, name=item.name); db.add(obj)
        obj.name, obj.image_url, obj.bio = item.name, item.image_url, item.bio
        obj.aliases = ", ".join(item.aliases) or obj.aliases
        # Credited performers are listed automatically, but monitoring is always
        # explicit. Scene/movie metadata refreshes must never turn monitoring on.
        obj.is_library = True
        scene.performers.append(obj)
    scene.tags = []
    for item in remote.tags:
        obj = db.scalar(select(Tag).where(Tag.tpdb_id == item.id))
        if not obj: obj = Tag(tpdb_id=item.id, name=item.name); db.add(obj)
        obj.name = item.name; scene.tags.append(obj)
    db.flush()
    db.add(History(event_type="scene_imported" if created else "metadata_refreshed", scene_id=scene.id, message=f"{'Imported' if created else 'Refreshed'} {scene.title}"))
    db.commit(); db.refresh(scene)
    return scene


def sync_adult_scene_entities_to_library(db: Session) -> dict[str, int]:
    """Repair/promote Adult scene credits into the performer/studio libraries.

    Older ScarletX builds already stored scene relationships, but studios were not
    necessarily marked as library entities.  Running this during startup makes an
    upgraded database immediately consistent without requiring every scene to be
    refreshed manually.
    """
    performer_ids = select(scene_performer.c.performer_id).join(Scene, Scene.id == scene_performer.c.scene_id).where(Scene.content_type == "scene")
    studio_ids = select(Scene.studio_id).where(Scene.content_type == "scene", Scene.studio_id.is_not(None))
    performer_result = db.execute(update(Performer).where(Performer.is_library.is_(False), Performer.id.in_(performer_ids)).values(is_library=True))
    studio_result = db.execute(update(Studio).where(Studio.is_library.is_(False), Studio.id.in_(studio_ids)).values(is_library=True))
    db.commit()
    return {"performers": performer_result.rowcount or 0, "studios": studio_result.rowcount or 0}


def repair_legacy_auto_monitored_adult_entities(db: Session) -> dict[str, int]:
    """Undo legacy auto-monitoring while preserving explicit user monitor requests.

    Builds before 0.7.16 marked every scene credit monitored.  We can distinguish
    most explicit user requests by their monitor-search jobs or direct import/monitor
    history. This one-time repair leaves all credited entities listed in the library.
    """
    marker = db.get(AppSetting, "adult_explicit_monitoring_0716_applied")
    if marker is not None:
        return {"performers_unmonitored": 0, "studios_unmonitored": 0}

    explicit_performer_ids: set[str] = set()
    explicit_studio_ids: set[str] = set()
    for job in db.scalars(select(BackgroundJob)).all():
        if job.kind not in {"performer_monitor_search", "studio_monitor_search"}:
            continue
        try:
            payload = __import__("json").loads(job.payload or "{}")
        except (TypeError, ValueError):
            payload = {}
        identifier = str(payload.get("identifier") or "")
        if not identifier:
            continue
        if job.kind == "performer_monitor_search":
            explicit_performer_ids.add(identifier)
        else:
            explicit_studio_ids.add(identifier)

    performer_names: set[str] = set()
    studio_names: set[str] = set()
    for event in db.scalars(select(History)).all():
        message = event.message or ""
        if event.event_type in {"performer_imported", "performer_monitoring_changed"}:
            if event.event_type == "performer_imported" and message.startswith("Imported performer "):
                performer_names.add(message.removeprefix("Imported performer "))
            elif message.startswith("Monitored performer "):
                performer_names.add(message.removeprefix("Monitored performer "))
        if event.event_type in {"studio_imported", "studio_monitoring_changed"}:
            if event.event_type == "studio_imported" and message.startswith("Imported studio "):
                studio_names.add(message.removeprefix("Imported studio "))
            elif message.startswith("Monitored studio "):
                studio_names.add(message.removeprefix("Monitored studio "))

    performers_unmonitored = 0
    for performer in db.scalars(select(Performer).where(Performer.is_library.is_(True))).all():
        explicit = performer.tpdb_id in explicit_performer_ids or performer.name in performer_names
        if performer.monitored and not explicit:
            performer.monitored = False
            performers_unmonitored += 1

    studios_unmonitored = 0
    for studio in db.scalars(select(Studio).where(Studio.is_library.is_(True))).all():
        explicit = studio.tpdb_id in explicit_studio_ids or studio.name in studio_names
        if studio.monitored and not explicit:
            studio.monitored = False
            studios_unmonitored += 1

    db.add(AppSetting(key="adult_explicit_monitoring_0716_applied", value="true", is_secret=False))
    db.commit()
    return {
        "performers_unmonitored": performers_unmonitored,
        "studios_unmonitored": studios_unmonitored,
    }


def upsert_performer(db: Session, remote: RemotePerson, monitored: bool = True) -> Performer:
    obj = db.scalar(select(Performer).where(Performer.tpdb_id == remote.id))
    created = obj is None
    if not obj:
        obj = Performer(tpdb_id=remote.id, name=remote.name); db.add(obj)
    obj.name, obj.image_url, obj.bio = remote.name, remote.image_url, remote.bio
    obj.aliases = ", ".join(remote.aliases) or None
    obj.monitored, obj.is_library = monitored, True
    db.flush(); db.add(History(event_type="performer_imported" if created else "metadata_refreshed", message=f"Imported performer {obj.name}")); db.commit(); db.refresh(obj)
    return obj


def upsert_studio(db: Session, remote: RemoteStudio, monitored: bool = True) -> Studio:
    obj = db.scalar(select(Studio).where(Studio.tpdb_id == remote.id))
    created = obj is None
    if not obj:
        obj = Studio(tpdb_id=remote.id, name=remote.name); db.add(obj)
    obj.name, obj.url, obj.logo_url = remote.name, remote.url, remote.logo_url
    obj.poster_url, obj.description = remote.poster_url, remote.description
    obj.monitored, obj.is_library = monitored, True
    db.flush(); db.add(History(event_type="studio_imported" if created else "metadata_refreshed", message=f"Imported studio {obj.name}")); db.commit(); db.refresh(obj)
    return obj
