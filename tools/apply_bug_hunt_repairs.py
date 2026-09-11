from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def sub_once(text: str, pattern: str, replacement: str, label: str) -> str:
    out, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one regex match, got {count}")
    return out


# --- Frontend: remove stale function forks and make core code authoritative. ---
write(
    "frontend/studio_art_overrides.js",
    "const STUDIO_ART_HTTP_VERSION='v5';\n"
    "studioArtUrl=function(id){return `/api/artwork/studios/${encodeURIComponent(id)}?v=${STUDIO_ART_HTTP_VERSION}`;};\n",
)
write(
    "frontend/dashboard_settings_overrides.js",
    "// Retained as a packaged compatibility asset. Core dashboard, library rows, and settings\n"
    "// now live in app.js/ui_overrides.js so late-loaded stale copies cannot undo fixes.\n",
)

app = read("frontend/app.js")
app = once(
    app,
    "const fmtDate=v=>v?new Date(v).toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'}):'—';",
    "const fmtDate=v=>{if(!v)return'—';let s=String(v),d;if(/^\\d{4}-\\d{2}-\\d{2}$/.test(s)){let [y,m,day]=s.split('-').map(Number);d=new Date(y,m-1,day)}else d=new Date(v);return d.toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'})};",
    "date-only formatter",
)

profile_helpers = r'''async function loadAllPerformerScenes(id,localId=null){
  let items=[],page=1,total=0;
  while(page<=1000){let url=localId?`/api/library/performers/${encodeURIComponent(localId)}/scenes?page=${page}&per_page=100`:`/api/metadata/performers/${encodeURIComponent(id)}/scenes?page=${page}&per_page=100`;let result=await api(url);let rows=result.items||[];items.push(...rows);total=Number(result.total||items.length);if(page*Number(result.per_page||100)>=total)break;page++}
  return {items,total:items.length};
}
async function loadAllStudioScenes(id,localId=null){
  let items=[],page=1,total=0;
  while(page<=1000){let url=localId?`/api/library/studios/${encodeURIComponent(localId)}/scenes?page=${page}&per_page=100`:`/api/metadata/studios/${encodeURIComponent(id)}/scenes?page=${page}&per_page=100`;let result=await api(url);let rows=result.items||[];items.push(...rows);total=Number(result.total||items.length);if(page*Number(result.per_page||100)>=total)break;page++}
  return {items,total:items.length};
}
function localPerformerProfile(x){let aliases=x.aliases;if(typeof aliases==='string')aliases=aliases.split(',').map(v=>v.trim()).filter(Boolean);let links=x.links||{};return {...x,id:x.tpdb_id,aliases:aliases||[],links};}

'''
app = once(app, "async function performerProfile(id,localId=null){", profile_helpers + "async function performerProfile(id,localId=null){", "profile helpers")

performer_fn = r'''async function performerProfile(id,localId=null){
  const generation=nextNavigationGeneration();
  $('#app').innerHTML=pageHead('Performer','Loading performer profile…',`<button class="btn" id="backPerformers">← Performers</button>`)+`<div class="empty">Loading performer information…</div>`;
  $('#backPerformers').onclick=()=>{view='performers';renderEntities('performers')};
  try{
    let local=null;
    if(localId){try{local=await api(`/api/library/performers/${encodeURIComponent(localId)}/detail`)}catch(_){}}
    else{let cached=entityLibraryCache.performers?.items||[],summary=cached.find(v=>String(v.tpdb_id)===String(id))||null;if(summary?.id){try{local=await api(`/api/library/performers/${encodeURIComponent(summary.id)}/detail`)}catch(_){local=summary}}}
    let resolvedLocalId=localId||local?.id||null;
    let x=local?localPerformerProfile(local):await api(`/api/metadata/performers/${encodeURIComponent(id)}`);
    let scenes={items:[]};try{scenes=await loadAllPerformerScenes(id,resolvedLocalId)}catch(_){}
    let img=x.image_url?`/api/artwork/performers/${encodeURIComponent(id)}`:'';let links=Object.entries(x.links||{}).filter(([,v])=>v).map(([k,v])=>`<a class="btn small" target="_blank" rel="noopener" href="${esc(v)}">${esc(k)}</a>`).join('');
    if(!navigationGenerationCurrent(generation))return;$('#app').innerHTML=pageHead(x.name||'Performer','Cached performer profile',`<button class="btn" id="backPerformers">← Performers</button>${local?.monitored?'':`<button class="btn primary" id="monitorAllPerformer">Monitor All</button>`}`)+`<div class="profile-shell"><div class="profile-image">${img?`<img src="${esc(img)}" alt="${esc(x.name||'Performer')}" loading="eager" onerror="this.remove()">`:'No performer image available.'}</div><div><div class="profile-facts">${performerFacts(x,local?local.monitored:null)}</div>${x.bio?`<div class="profile-section"><h2>Biography</h2><div class="profile-bio">${esc(x.bio)}</div></div>`:''}${links?`<div class="profile-section"><h2>Links</h2><div class="profile-links">${links}</div></div>`:''}</div></div><div class="profile-section"><h2>Studio Scenes</h2><div id="performerSceneList">${sceneProfileList(scenes.items||[])}</div></div>`;
    $('#backPerformers').onclick=()=>{view='performers';renderEntities('performers')};if($('#monitorAllPerformer'))$('#monitorAllPerformer').onclick=async e=>{try{await monitorAllEntity('performers',id,resolvedLocalId,e.currentTarget)}catch(err){notify(err.message,'error')}};bindProfileSceneLinks($('#performerSceneList'));
  }catch(e){if(!navigationGenerationCurrent(generation))return;notify(e.message,'error');if(!navigationGenerationCurrent(generation))return;$('#app').innerHTML=pageHead('Performer','Unable to load performer profile.',`<button class="btn" id="backPerformers">← Performers</button>`)+empty(e.message);$('#backPerformers').onclick=()=>{view='performers';renderEntities('performers')}}
}'''
app = sub_once(app, r"async function performerProfile\(id,localId=null\)\{.*?(?=\n\nasync function studioProfile)", performer_fn, "performer profile")

studio_fn = r'''async function studioProfile(id,localId=null){
  const generation=nextNavigationGeneration();
  $('#app').innerHTML=pageHead('Studio','Loading studio…',`<button class="btn" id="backStudios">← Studios</button>`)+empty('Loading studio information…');
  $('#backStudios').onclick=()=>{view='studios';renderEntities('studios')};
  try{
    let local=null;
    if(localId){try{local=await api(`/api/library/studios/${encodeURIComponent(localId)}/detail`)}catch(_){}}
    else{let cached=entityLibraryCache.studios?.items||[],summary=cached.find(v=>String(v.tpdb_id)===String(id))||null;if(summary?.id){try{local=await api(`/api/library/studios/${encodeURIComponent(summary.id)}/detail`)}catch(_){local=summary}}}
    let resolvedLocalId=localId||local?.id||null;
    let x=local?{...local,id:local.tpdb_id}:await api(`/api/metadata/studios/${encodeURIComponent(id)}`);
    let scenes={items:[]};try{scenes=await loadAllStudioScenes(id,resolvedLocalId)}catch(_){}
    let img=(x.poster_url||x.logo_url||x.image_url)?`/api/artwork/studios/${encodeURIComponent(id)}`:'';
    if(!navigationGenerationCurrent(generation))return;$('#app').innerHTML=pageHead(x.name||'Studio','Cached studio profile',`<button class="btn" id="backStudios">← Studios</button>${local?.monitored?'':`<button class="btn primary" id="monitorAllStudio">Monitor All</button>`}`)+`<div class="profile-shell"><div class="profile-image">${img?`<img src="${esc(img)}" alt="${esc(x.name||'Studio')}" loading="eager" onerror="this.remove()">`:'No studio image available.'}</div><div><div class="profile-facts"><div class="profile-fact"><b>Monitored</b><span>${local?.monitored?'Yes':'No'}</span></div>${x.url?`<div class="profile-fact"><b>Website</b><span><a target="_blank" rel="noopener" href="${esc(x.url)}">Open site</a></span></div>`:''}</div>${x.description?`<div class="profile-section"><h2>About</h2><div class="profile-bio">${esc(x.description)}</div></div>`:''}</div></div><div class="profile-section"><h2>Studio Scenes</h2><div id="studioSceneList">${sceneProfileList(scenes.items||[])}</div></div>`;
    $('#backStudios').onclick=()=>{view='studios';renderEntities('studios')};if($('#monitorAllStudio'))$('#monitorAllStudio').onclick=async e=>{try{await monitorAllEntity('studios',id,resolvedLocalId,e.currentTarget)}catch(err){notify(err.message,'error')}};bindProfileSceneLinks($('#studioSceneList'));
  }catch(e){if(!navigationGenerationCurrent(generation))return;notify(e.message,'error');if(!navigationGenerationCurrent(generation))return;$('#app').innerHTML=pageHead('Studio','Unable to load studio.',`<button class="btn" id="backStudios">← Studios</button>`)+empty(e.message);$('#backStudios').onclick=()=>{view='studios';renderEntities('studios')}}
}'''
app = sub_once(app, r"async function studioProfile\(id,localId=null\)\{.*?(?=\n\n\nasync function openLocalScene)", studio_fn, "studio profile")

app = once(
    app,
    "    try{remote=await api(`/api/metadata/scenes/${encodeURIComponent(id)}`)}catch(_){remote=null}\n    let x={...(local||{}),...(remote||{})},files=local?.files||[];",
    "    if(!local){try{remote=await api(`/api/metadata/scenes/${encodeURIComponent(id)}`)}catch(_){remote=null}}\n    let x=local||remote||{},files=local?.files||[];",
    "scene local-first detail",
)
write("frontend/app.js", app)

# --- TPDB monitored discovery: no 50-page truncation, no empty-filter early stop. ---
mon = read("scarletx/monitored_entities.py")
mon = once(mon, "MAX_ENTITY_PAGES = 50", "MAX_ENTITY_PAGES = 1000", "entity page cap")
mon = mon.replace("        if not response.items or page * response.per_page >= response.total:\n            break", "        if page * response.per_page >= response.total:\n            break")
mon = once(
    mon,
    "    studio = await tpdb.get_studio(identifier)\n    if studio.search_id is None:\n        raise RuntimeError(f\"Studio {identifier} has no searchable TPDB site ID\")\n    first = await tpdb.search_scenes(page=1, per_page=ENTITY_PAGE_SIZE, site_id=str(studio.search_id))",
    "    studio = await tpdb.get_studio(identifier)\n    search_id = studio.search_id\n    if search_id is None and identifier.isdigit():\n        search_id = int(identifier)\n    if search_id is None:\n        raise RuntimeError(f\"Studio {identifier} has no searchable TPDB site ID\")\n    first = await tpdb.search_scenes(page=1, per_page=ENTITY_PAGE_SIZE, site_id=str(search_id))",
    "studio numeric fallback",
)
mon = mon.replace('            site_id=str(studio.search_id),', '            site_id=str(search_id),')
write("scarletx/monitored_entities.py", mon)

# --- Persist the complete performer profile rather than a sparse shell. ---
models = read("scarletx/models.py")
performer_old = '''    aliases: Mapped[str | None] = mapped_column(Text)\n    monitored: Mapped[bool] = mapped_column(Boolean, default=False)'''
performer_new = '''    aliases: Mapped[str | None] = mapped_column(Text)\n    gender: Mapped[str | None] = mapped_column(String(100))\n    birthday: Mapped[date | None] = mapped_column(Date)\n    deathday: Mapped[date | None] = mapped_column(Date)\n    birthplace: Mapped[str | None] = mapped_column(String(500))\n    birthplace_code: Mapped[str | None] = mapped_column(String(100))\n    nationality: Mapped[str | None] = mapped_column(String(200))\n    ethnicity: Mapped[str | None] = mapped_column(String(200))\n    measurements: Mapped[str | None] = mapped_column(String(200))\n    cup_size: Mapped[str | None] = mapped_column(String(100))\n    fake_boobs: Mapped[bool | None] = mapped_column(Boolean)\n    waist: Mapped[str | None] = mapped_column(String(100))\n    hips: Mapped[str | None] = mapped_column(String(100))\n    same_sex_only: Mapped[bool | None] = mapped_column(Boolean)\n    status: Mapped[str | None] = mapped_column(String(100))\n    height: Mapped[str | None] = mapped_column(String(100))\n    weight: Mapped[str | None] = mapped_column(String(100))\n    hair_color: Mapped[str | None] = mapped_column(String(100))\n    eye_color: Mapped[str | None] = mapped_column(String(100))\n    tattoos: Mapped[str | None] = mapped_column(Text)\n    piercings: Mapped[str | None] = mapped_column(Text)\n    astrology: Mapped[str | None] = mapped_column(String(100))\n    career_start_year: Mapped[int | None] = mapped_column(Integer)\n    career_end_year: Mapped[int | None] = mapped_column(Integer)\n    links_json: Mapped[str | None] = mapped_column(Text)\n    monitored: Mapped[bool] = mapped_column(Boolean, default=False)'''
models = once(models, performer_old, performer_new, "performer model fields")
write("scarletx/models.py", models)

services = read("scarletx/services.py")
services = once(services, "from sqlalchemy import select, update", "import json\n\nfrom sqlalchemy import select, update", "services json import")
helper = '''\n\ndef _apply_performer_metadata(obj: Performer, item: RemotePerson) -> None:\n    obj.name = item.name\n    obj.image_url = item.image_url\n    obj.bio = item.bio\n    obj.aliases = ", ".join(item.aliases) or None\n    for field in (\n        "gender", "birthday", "deathday", "birthplace", "birthplace_code",\n        "nationality", "ethnicity", "measurements", "cup_size", "fake_boobs",\n        "waist", "hips", "same_sex_only", "status", "height", "weight",\n        "hair_color", "eye_color", "tattoos", "piercings", "astrology",\n        "career_start_year", "career_end_year",\n    ):\n        setattr(obj, field, getattr(item, field, None))\n    obj.links_json = json.dumps(item.links or {}, separators=(",", ":"))\n'''
services = once(services, "\n\ndef upsert_scene(", helper + "\n\ndef upsert_scene(", "performer metadata helper")
services = once(
    services,
    "        obj.name, obj.image_url, obj.bio = item.name, item.image_url, item.bio\n        obj.aliases = \", \".join(item.aliases) or obj.aliases",
    "        _apply_performer_metadata(obj, item)",
    "scene performer metadata",
)
services = once(
    services,
    "    obj.name, obj.image_url, obj.bio = remote.name, remote.image_url, remote.bio\n    obj.aliases = \", \".join(remote.aliases) or None",
    "    _apply_performer_metadata(obj, remote)",
    "performer upsert metadata",
)
write("scarletx/services.py", services)

# --- Media processing: cap heavy tools and eliminate shared temp-file race. ---
media = read("scarletx/media_library.py")
media = once(media, "import subprocess", "import subprocess\nimport uuid", "media uuid import")
media = once(media, "workers = min(4, max(1, (os.cpu_count() or 2) // 2), len(to_index))", "workers = min(2, max(1, (os.cpu_count() or 2) // 2), len(to_index))", "media worker cap")
media = once(media, 'temporary = root / "playback.tmp.mp4"', 'temporary = root / f"playback.{uuid.uuid4().hex}.tmp.mp4"', "playback unique temp")
write("scarletx/media_library.py", media)

# --- Event-driven downloader/import wakeups with recovery timers. ---
write("scarletx/background_signals.py", '''from __future__ import annotations\n\nimport asyncio\nimport threading\n\n\nclass AsyncWakeSignal:\n    def __init__(self) -> None:\n        self._lock = threading.Lock()\n        self._loop: asyncio.AbstractEventLoop | None = None\n        self._event: asyncio.Event | None = None\n\n    async def bind(self) -> None:\n        loop = asyncio.get_running_loop()\n        with self._lock:\n            if self._loop is not loop or self._event is None:\n                self._loop = loop\n                self._event = asyncio.Event()\n\n    def notify(self) -> bool:\n        with self._lock:\n            loop, event = self._loop, self._event\n        if loop is None or event is None or loop.is_closed():\n            return False\n        loop.call_soon_threadsafe(event.set)\n        return True\n\n    async def wait(self, timeout: float) -> bool:\n        await self.bind()\n        assert self._event is not None\n        if self._event.is_set():\n            self._event.clear(); return True\n        try:\n            await asyncio.wait_for(self._event.wait(), timeout=timeout)\n        except TimeoutError:\n            return False\n        self._event.clear(); return True\n\n\nnative_queue_signal = AsyncWakeSignal()\ncompleted_import_signal = AsyncWakeSignal()\n''')
worker = read("scarletx/usenet/worker.py")
worker = once(worker, "from ..archive_security import parse_7z_listing, validate_archive_member_path, validate_extracted_tree", "from ..archive_security import parse_7z_listing, validate_archive_member_path, validate_extracted_tree\nfrom ..background_signals import completed_import_signal, native_queue_signal", "worker signals import")
worker = once(worker, "\n\nclass NativeUsenetError", "\n\nNATIVE_QUEUE_RECOVERY_SECONDS = 60\n\n\nclass NativeUsenetError", "worker recovery constant")
worker = once(worker, "        if existing:\n            return existing.id", "        if existing:\n            native_queue_signal.notify()\n            return existing.id", "existing queue wake")
worker = once(worker, "        db.commit()\n    return job_id\n\n\n\nasync def reprocess_completed_job", "        db.commit()\n    native_queue_signal.notify()\n    return job_id\n\n\n\nasync def reprocess_completed_job", "new queue wake")
worker = once(worker, "        unpack_password=None,\n    )\n    with session_factory() as db:", "        unpack_password=None,\n    )\n    completed_import_signal.notify()\n    with session_factory() as db:", "reprocess completion wake")
worker = once(worker, "                unpack_password=None,\n            )\n            _clear_live_progress(job_id)", "                unpack_password=None,\n            )\n            completed_import_signal.notify()\n            _clear_live_progress(job_id)", "download completion wake")
worker = once(worker, '    emit_status("Native Downloader", "ACTIVE", f"poll every {poll_seconds:g}s", severity="active")', '    emit_status("Native Downloader", "ACTIVE", "event driven; 60s recovery fallback", severity="active")\n    await native_queue_signal.bind()', "native loop bind")
worker = once(worker, "        if not job_id:\n            await asyncio.sleep(poll_seconds)\n            continue", "        if not job_id:\n            await native_queue_signal.wait(NATIVE_QUEUE_RECOVERY_SECONDS)\n            continue", "native loop wait")
write("scarletx/usenet/worker.py", worker)

# --- Application routes, migration, cached profile scene paging, restart recovery. ---
application = read("scarletx/routes/application.py")
application = once(application, "    UserTag, Webhook, library_user_tag, utcnow,", "    UserTag, Webhook, library_user_tag, scene_performer, utcnow,", "scene performer import")
application = once(application, "from ..entity_hydration import queue_adult_entity_hydration as _queue_adult_entity_hydration", "from ..entity_hydration import queue_adult_entity_hydration as _queue_adult_entity_hydration, run_adult_entity_hydration", "hydration runner import")
application = once(application, "from ..event_stream import QueueEvent, format_sse, queue_event_broker, queue_event_pump", "from ..event_stream import QueueEvent, format_sse, queue_event_broker, queue_event_pump\nfrom ..background_signals import completed_import_signal", "application signal import")
application = once(application, "MONITORED_ENTITY_DISCOVERY_INTERVAL_SECONDS = 3600", "COMPLETED_IMPORT_RECOVERY_SECONDS = 120\nMONITORED_ENTITY_DISCOVERY_INTERVAL_SECONDS = 3600", "completed recovery constant")

# Existing SQLite installations need the new performer cache columns.
migration_anchor = '            legacy_tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type=\'table\'")}\n'
migration_insert = migration_anchor + '''            if "performers" in legacy_tables:\n                performer_columns = {row[1] for row in cur.execute("PRAGMA table_info(performers)")}\n                performer_additions = {\n                    "gender": "VARCHAR(100)", "birthday": "DATE", "deathday": "DATE",\n                    "birthplace": "VARCHAR(500)", "birthplace_code": "VARCHAR(100)",\n                    "nationality": "VARCHAR(200)", "ethnicity": "VARCHAR(200)",\n                    "measurements": "VARCHAR(200)", "cup_size": "VARCHAR(100)",\n                    "fake_boobs": "BOOLEAN", "waist": "VARCHAR(100)", "hips": "VARCHAR(100)",\n                    "same_sex_only": "BOOLEAN", "status": "VARCHAR(100)",\n                    "height": "VARCHAR(100)", "weight": "VARCHAR(100)",\n                    "hair_color": "VARCHAR(100)", "eye_color": "VARCHAR(100)",\n                    "tattoos": "TEXT", "piercings": "TEXT", "astrology": "VARCHAR(100)",\n                    "career_start_year": "INTEGER", "career_end_year": "INTEGER", "links_json": "TEXT",\n                }\n                for column, sql_type in performer_additions.items():\n                    if column not in performer_columns:\n                        cur.execute(f"ALTER TABLE performers ADD COLUMN {column} {sql_type}")\n'''
application = once(application, migration_anchor, migration_insert, "performer sqlite migration")

resume_helper = '''\n\nasync def resume_background_jobs(settings: Settings) -> list[asyncio.Task]:\n    """Resume durable long-running work that was interrupted by a restart."""\n    resumable: list[tuple[int, str, dict]] = []\n    with SessionLocal() as db:\n        jobs = db.scalars(select(BackgroundJob).where(BackgroundJob.status.in_(("queued", "running"))).order_by(BackgroundJob.id)).all()\n        for job in jobs:\n            try:\n                payload = json.loads(job.payload or "{}")\n            except (TypeError, json.JSONDecodeError):\n                payload = {}\n            if job.kind in {"performer_metadata_hydration", "studio_metadata_hydration", "performer_monitor_search", "studio_monitor_search", "media_library_scan"}:\n                job.status = "queued"\n                job.error = None\n                job.finished_at = None\n                resumable.append((job.id, job.kind, payload))\n            else:\n                job.status = "failed"\n                job.error = "Interrupted by application restart; this job type is not resumable"\n                job.finished_at = utcnow()\n        db.commit()\n    tasks: list[asyncio.Task] = []\n    for job_id, kind, payload in resumable:\n        if kind.endswith("_metadata_hydration"):\n            entity_type = str(payload.get("entity_type") or kind.split("_", 1)[0])\n            identifier = str(payload.get("identifier") or "")\n            if identifier:\n                tasks.append(asyncio.create_task(run_adult_entity_hydration(job_id, entity_type, identifier, settings, bool(payload.get("search_when_monitored")))))\n        elif kind.endswith("_monitor_search"):\n            entity_type = str(payload.get("entity_type") or kind.split("_", 1)[0])\n            identifier = str(payload.get("identifier") or "")\n            if identifier:\n                tasks.append(asyncio.create_task(run_adult_entity_monitor_search(job_id, entity_type, identifier, settings)))\n        elif kind == "media_library_scan":\n            tasks.append(asyncio.create_task(_run_media_scan(job_id)))\n    return tasks\n'''
application = once(application, "\n\ndownloader_supervisor = DownloaderSupervisor(SessionLocal, _runtime_settings_loader)\n", resume_helper + "\n\ndownloader_supervisor = DownloaderSupervisor(SessionLocal, _runtime_settings_loader)\n", "resume helper")
application = sub_once(application, r"    with SessionLocal\(\) as db:\n        # In-process background tasks cannot survive.*?        seed_database_settings\(db\)", "    with SessionLocal() as db:\n        seed_database_settings(db)", "remove interrupted failure block")
application = once(application, "    await downloader_supervisor.start()\n    watchers = [", "    await downloader_supervisor.start()\n    recovered_watchers = await resume_background_jobs(runtime)\n    watchers = recovered_watchers + [", "resume startup")

# Event-driven completed import loop.
application = sub_once(
    application,
    r"async def completed_download_import_loop\(\) -> None:\n.*?(?=\n\nasync def automatic_search_loop)",
    '''async def completed_download_import_loop() -> None:\n    await completed_import_signal.bind()\n    while True:\n        wait_seconds = COMPLETED_IMPORT_RECOVERY_SECONDS\n        try:\n            result = await process_completed_downloads()\n            wait_seconds = min(COMPLETED_IMPORT_RECOVERY_SECONDS, max(1, int(result.get("poll_seconds", COMPLETED_IMPORT_RECOVERY_SECONDS))))\n        except asyncio.CancelledError:\n            raise\n        except Exception:\n            wait_seconds = COMPLETED_IMPORT_RECOVERY_SECONDS\n        await completed_import_signal.wait(wait_seconds)''',
    "completed import signal loop",
)
application = once(application, "    today = datetime.now(UTC).date(); start = start or today; end = end or (today + timedelta(days=90))", "    today = date.today(); start = start or today; end = end or (today + timedelta(days=90))", "calendar local date")

# Full cached performer detail serializer.
performer_detail_old = '    return {"id":x.id,"tpdb_id":x.tpdb_id,"name":x.name,"image_url":x.image_url,"bio":x.bio,"aliases":x.aliases,"monitored":x.monitored}'
performer_detail_new = '''    try:\n        links = json.loads(x.links_json or "{}")\n    except (TypeError, json.JSONDecodeError):\n        links = {}\n    birthday = x.birthday\n    deathday = x.deathday\n    age = None\n    if birthday:\n        end = deathday or date.today()\n        age = end.year - birthday.year - ((end.month, end.day) < (birthday.month, birthday.day))\n    return {\n        "id":x.id,"tpdb_id":x.tpdb_id,"name":x.name,"image_url":x.image_url,"bio":x.bio,"aliases":x.aliases,"monitored":x.monitored,\n        "gender":x.gender,"birthday":x.birthday,"deathday":x.deathday,"age":age,"birthplace":x.birthplace,"birthplace_code":x.birthplace_code,\n        "nationality":x.nationality,"ethnicity":x.ethnicity,"measurements":x.measurements,"cup_size":x.cup_size,"fake_boobs":x.fake_boobs,\n        "waist":x.waist,"hips":x.hips,"same_sex_only":x.same_sex_only,"status":x.status,"height":x.height,"weight":x.weight,\n        "hair_color":x.hair_color,"eye_color":x.eye_color,"tattoos":x.tattoos,"piercings":x.piercings,"astrology":x.astrology,\n        "career_start_year":x.career_start_year,"career_end_year":x.career_end_year,"links":links,\n    }'''
application = once(application, performer_detail_old, performer_detail_new, "performer detail full cache")
application = once(application, 'return {"id":x.id,"tpdb_id":x.tpdb_id,"name":x.name,"image_url":x.poster_url or x.logo_url,"url":x.url,"description":x.description,"monitored":x.monitored}', 'return {"id":x.id,"tpdb_id":x.tpdb_id,"name":x.name,"image_url":x.poster_url or x.logo_url,"poster_url":x.poster_url,"logo_url":x.logo_url,"url":x.url,"description":x.description,"monitored":x.monitored}', "studio detail cache")

cached_scene_routes = '''\n\ndef _cached_profile_scene_page(db: Session, stmt, page: int, per_page: int) -> dict:\n    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)\n    scenes = db.scalars(stmt.options(selectinload(Scene.studio), selectinload(Scene.performers)).order_by(Scene.release_date.desc(), Scene.id.desc()).offset((page-1)*per_page).limit(per_page)).unique().all()\n    scene_ids = [scene.id for scene in scenes]\n    media = {}\n    if scene_ids:\n        for row in db.scalars(select(MediaFile).where(MediaFile.scene_id.in_(scene_ids)).order_by(MediaFile.imported_at.desc())).all():\n            media.setdefault(row.scene_id, row)\n    items=[]\n    for scene in scenes:\n        file = media.get(scene.id)\n        items.append({\n            "id":scene.tpdb_id,"tpdb_id":scene.tpdb_id,"local_id":scene.id,"title":scene.title,"description":scene.description,\n            "release_date":scene.release_date,"duration":scene.duration,"image_url":scene.image_url,"back_image_url":scene.back_image_url,"poster_url":scene.poster_url,\n            "studio":{"id":scene.studio.tpdb_id,"name":scene.studio.name,"logo_url":scene.studio.logo_url} if scene.studio else None,\n            "performers":[{"id":p.tpdb_id,"name":p.name,"image_url":p.image_url} for p in scene.performers],\n            "monitored":scene.monitored,"media_id":file.id if file else None,"download_status":"Downloaded" if file else ("Monitored" if scene.monitored else "Available"),\n        })\n    return {"items":items,"total":total,"page":page,"per_page":per_page}\n\n\n@app.get("/api/library/performers/{item_id}/scenes")\ndef performer_cached_scenes(item_id:int,page:int=Query(1,ge=1),per_page:int=Query(100,ge=1,le=200),db:Session=Depends(get_session)):\n    performer=db.get(Performer,item_id)\n    if not performer or not performer.is_library: raise HTTPException(404,"Performer not found in library")\n    stmt=select(Scene).join(scene_performer,Scene.id==scene_performer.c.scene_id).where(scene_performer.c.performer_id==item_id,Scene.content_type=="scene")\n    return _cached_profile_scene_page(db,stmt,page,per_page)\n\n\n@app.get("/api/library/studios/{item_id}/scenes")\ndef studio_cached_scenes(item_id:int,page:int=Query(1,ge=1),per_page:int=Query(100,ge=1,le=200),db:Session=Depends(get_session)):\n    studio=db.get(Studio,item_id)\n    if not studio or not studio.is_library: raise HTTPException(404,"Studio not found in library")\n    stmt=select(Scene).where(Scene.studio_id==item_id,Scene.content_type=="scene")\n    return _cached_profile_scene_page(db,stmt,page,per_page)\n'''
application = once(application, "\n\n@app.get(\"/api/manual-import/scan\")", cached_scene_routes + "\n\n@app.get(\"/api/manual-import/scan\")", "cached profile scene routes")
write("scarletx/routes/application.py", application)

# --- Retire tests that asserted stale override copies; test final authority instead. ---
ui_test = read("tests/test_ui_theme.py")
ui_test = sub_once(
    ui_test,
    r"def test_library_runtime_media_spec_puts_duration_on_its_own_line\(\):.*?(?=\n\ndef test_scene_rows_show_tpdb_artwork_studio_logo_and_play_control)",
    '''def test_library_runtime_uses_single_authoritative_media_renderer():\n    source = (FRONTEND / "dashboard_settings_overrides.js").read_text(encoding="utf-8")\n    overrides = (FRONTEND / "ui_overrides.js").read_text(encoding="utf-8")\n    assert "mediaFileRowsHtml=function(files)" not in source\n    assert "function mediaFileRowsHtml(files)" in overrides\n    assert 'class="library-release"' in overrides\n''',
    "stale media renderer test",
)
write("tests/test_ui_theme.py", ui_test)

studio_test = read("tests/test_studio_art_consistency.py")
studio_test = sub_once(
    studio_test,
    r"def test_studio_cards_always_request_standardized_tpdb_artwork\(\):.*?(?=\n\ndef test_small_studio_logos_use_prepared_artwork_background_without_forcing_gray)",
    '''def test_studio_art_override_only_versions_artwork_and_does_not_replace_core_renderers():\n    override_path = ROOT / "frontend" / "studio_art_overrides.js"\n    source = override_path.read_text(encoding="utf-8")\n    css = (ROOT / "frontend" / "ui_overrides.css").read_text(encoding="utf-8")\n    assert "STUDIO_ART_HTTP_VERSION='v5'" in source\n    assert "studioArtUrl=function(id)" in source\n    assert "?v=${STUDIO_ART_HTTP_VERSION}" in source\n    assert "studioLink=function" not in source\n    assert "entityCard=function" not in source\n    assert ".studio-card .media-poster{aspect-ratio:16/7" in css\n    assert ".studio-card .media-poster img{object-fit:contain" in css\n''',
    "stale studio override test",
)
write("tests/test_studio_art_consistency.py", studio_test)

print("Applied ScarletX bug-hunt repairs")
