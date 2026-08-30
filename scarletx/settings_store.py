from __future__ import annotations
import json
import threading
import time
from pydantic import SecretStr
from sqlalchemy.orm import Session
from .config import DEFAULT_ADULT_INDEXER_CATEGORIES, DEV_NZBGEEK_API_KEY, DEV_NZBGEEK_API_URL, DEV_TREASURE_MAPS_API_KEY, DEV_TREASURE_MAPS_API_URL, DEV_NZBLIFE_API_KEY, DEV_NZBLIFE_API_URL, DEV_USENET_CRAWLER_API_KEY, DEV_USENET_CRAWLER_API_URL, DEV_ASTRAWEB_HOST, DEV_ASTRAWEB_PORT, DEV_ASTRAWEB_USERNAME, DEV_ASTRAWEB_PASSWORD, DEV_ASTRAWEB_CONNECTIONS, DEV_NEWSHOSTING_HOST, DEV_NEWSHOSTING_PORT, DEV_NEWSHOSTING_USERNAME, DEV_NEWSHOSTING_PASSWORD, DEV_NEWSHOSTING_CONNECTIONS, Settings
from .models import AppSetting

SECRET_KEYS={"theporndb_api_key","newznab_indexers_json","native_usenet_providers_json","api_key"}
_SETTINGS_CACHE_LOCK=threading.RLock()
_SETTINGS_CACHE={}
_SETTINGS_CACHE_TTL=5.0

def _cache_key(db):
    try: return id(db.get_bind())
    except Exception: return 0

def invalidate_settings_cache(db=None):
    with _SETTINGS_CACHE_LOCK:
        if db is None: _SETTINGS_CACHE.clear()
        else: _SETTINGS_CACHE.pop(_cache_key(db), None)

LEGACY_KEYS={
 "tmdb_api_token","tmdb_base_url","tmdb_image_base_url","tmdb_language","adult_enabled",
 "movie_naming_template","tv_naming_template","qbittorrent_enabled","qbittorrent_url",
 "qbittorrent_username","qbittorrent_password","qbittorrent_category","dev_defaults_0710_applied",
 "download_client_mode","sabnzbd_url","sabnzbd_api_key","sabnzbd_category","sabnzbd_priority","dev_sabnzbd_084_applied"
}

def default_setting_values():
    d=Settings()
    return {
      "app_name":d.app_name,"theporndb_api_key":d.theporndb_api_key.get_secret_value(),"theporndb_base_url":d.theporndb_base_url,
      "newznab_indexers_json":d.newznab_indexers_json.get_secret_value(),
      "native_usenet_enabled":"true" if d.native_usenet_enabled else "false",
      "native_usenet_providers_json":d.native_usenet_providers_json.get_secret_value(),"native_usenet_incomplete_dir":d.native_usenet_incomplete_dir,
      "native_usenet_complete_dir":d.native_usenet_complete_dir,"native_usenet_max_connections":str(d.native_usenet_max_connections),
      "native_usenet_max_retries":str(d.native_usenet_max_retries),"native_usenet_speed_limit_mb_s":str(d.native_usenet_speed_limit_mb_s),"native_usenet_repair_enabled":"true" if d.native_usenet_repair_enabled else "false",
      "native_usenet_unpack_enabled":"true" if d.native_usenet_unpack_enabled else "false",
      "completed_download_import_enabled":"true" if d.completed_download_import_enabled else "false","download_poll_seconds":str(d.download_poll_seconds),
      "file_management_enabled":"true" if d.file_management_enabled else "false","scene_naming_template":d.scene_naming_template,
      "automatic_search_enabled":"true" if d.automatic_search_enabled else "false","automatic_search_interval_minutes":str(d.automatic_search_interval_minutes),
      "automatic_search_batch_size":str(d.automatic_search_batch_size),"rss_sync_enabled":"true" if d.rss_sync_enabled else "false",
      "rss_sync_interval_minutes":str(d.rss_sync_interval_minutes),"rss_max_releases_per_indexer":str(d.rss_max_releases_per_indexer),
      "rss_max_grabs_per_cycle":str(d.rss_max_grabs_per_cycle),"import_mode":d.import_mode,"recycle_bin_path":d.recycle_bin_path,
      "minimum_free_space_gb":str(d.minimum_free_space_gb),"backup_enabled":"true" if d.backup_enabled else "false",
      "backup_directory":d.backup_directory,"backup_interval_hours":str(d.backup_interval_hours),"backup_keep":str(d.backup_keep),
      "api_key_enabled":"true" if d.api_key_enabled else "false","api_key":d.api_key.get_secret_value(),"scarletx_log_level":d.scarletx_log_level,
    }

def set_setting(db,key,value,*,commit=True):
    item=db.get(AppSetting,key)
    if item is None:
        item=AppSetting(key=key,value=value,is_secret=key in SECRET_KEYS);db.add(item)
    else:
        item.value=value;item.is_secret=key in SECRET_KEYS
    if commit: db.commit()
    invalidate_settings_cache(db)

def seed_database_settings(db):
    # ScarletX local-dev preview: seed the baked TPDB development key only when
    # the database has no TPDB key. A user-saved key always wins.
    defaults = default_setting_values()
    for key,value in defaults.items():
        item = db.get(AppSetting,key)
        if item is None:
            set_setting(db,key,value,commit=False)
        elif key == "theporndb_api_key" and not (item.value or "").strip() and value:
            item.value = value
            item.is_secret = True
    oldlog=db.get(AppSetting,"scenecore_log_level")
    if oldlog and db.get(AppSetting,"scarletx_log_level") is None: set_setting(db,"scarletx_log_level",oldlog.value,commit=False)
    for key in LEGACY_KEYS:
        item=db.get(AppSetting,key)
        if item is not None: db.delete(item)
    # Force all retained indexers to Usenet/Newznab and adult categories only.
    idx=db.get(AppSetting,"newznab_indexers_json")
    if idx:
        try: rows=json.loads(idx.value or "[]")
        except Exception: rows=[]
        clean=[]
        for row in rows:
            if str(row.get("implementation","newznab")).lower() != "newznab": continue
            row=dict(row)
            if not row.get("adult_categories"): row["adult_categories"] = row.get("categories") or list(DEFAULT_ADULT_INDEXER_CATEGORIES)
            for old in ("implementation","categories","tv_categories","movie_categories"): row.pop(old,None)
            clean.append(row)
        idx.value=json.dumps(clean)

    # Local-dev seed: ensure NZBGeek is available once with the requested
    # development key. After this marker exists, user changes/removal in Settings win.
    marker=db.get(AppSetting,"dev_nzbgeek_083_applied")
    if marker is None and DEV_NZBGEEK_API_KEY:
        item=db.get(AppSetting,"newznab_indexers_json")
        try: rows=json.loads(item.value if item else "[]")
        except Exception: rows=[]
        match=None
        for row in rows:
            if str(row.get("name","")).strip().casefold()=="nzbgeek":
                match=row; break
        if match is None:
            rows.append({
                "name":"NZBGeek",
                "url":DEV_NZBGEEK_API_URL,
                "api_key":DEV_NZBGEEK_API_KEY,
                "adult_categories":list(DEFAULT_ADULT_INDEXER_CATEGORIES),
                "enabled":True,
                "rss_enabled":True,
                "priority":25,
            })
        else:
            if not str(match.get("url") or "").strip(): match["url"]=DEV_NZBGEEK_API_URL
            if not str(match.get("api_key") or "").strip(): match["api_key"]=DEV_NZBGEEK_API_KEY
            if not match.get("adult_categories"): match["adult_categories"]=list(DEFAULT_ADULT_INDEXER_CATEGORIES)
            match.setdefault("enabled",True); match.setdefault("rss_enabled",True); match.setdefault("priority",25)
        set_setting(db,"newznab_indexers_json",json.dumps(rows),commit=False)
        set_setting(db,"dev_nzbgeek_083_applied","true",commit=False)

    # Local-dev seed: ensure Treasure Maps is available once with the
    # requested development key. Explicit user edits/removal win afterward.
    tm_marker=db.get(AppSetting,"dev_treasure_maps_084_applied")
    if tm_marker is None and DEV_TREASURE_MAPS_API_KEY:
        item=db.get(AppSetting,"newznab_indexers_json")
        try: rows=json.loads(item.value if item else "[]")
        except Exception: rows=[]
        match=None
        for row in rows:
            if str(row.get("name","")).strip().casefold() in {"treasure maps","treasure-maps","scenenzbs"}:
                match=row; break
        if match is None:
            rows.append({
                "name":"Treasure Maps",
                "url":DEV_TREASURE_MAPS_API_URL,
                "api_key":DEV_TREASURE_MAPS_API_KEY,
                "adult_categories":list(DEFAULT_ADULT_INDEXER_CATEGORIES),
                "enabled":True,
                "rss_enabled":True,
                "priority":20,
            })
        else:
            match["name"]="Treasure Maps"
            if not str(match.get("url") or "").strip() or "scenenzbs.com" in str(match.get("url") or "").lower(): match["url"]=DEV_TREASURE_MAPS_API_URL
            if not str(match.get("api_key") or "").strip(): match["api_key"]=DEV_TREASURE_MAPS_API_KEY
            if not match.get("adult_categories"): match["adult_categories"]=list(DEFAULT_ADULT_INDEXER_CATEGORIES)
            match.setdefault("enabled",True); match.setdefault("rss_enabled",True); match.setdefault("priority",20)
        set_setting(db,"newznab_indexers_json",json.dumps(rows),commit=False)
        set_setting(db,"dev_treasure_maps_084_applied","true",commit=False)

    # Local-dev seed: ensure NZB.life is available once with the
    # requested development key. Explicit user edits/removal win afterward.
    nl_marker=db.get(AppSetting,"dev_nzblife_085_applied")
    if nl_marker is None and DEV_NZBLIFE_API_KEY:
        item=db.get(AppSetting,"newznab_indexers_json")
        try: rows=json.loads(item.value if item else "[]")
        except Exception: rows=[]
        match=None
        for row in rows:
            if str(row.get("name","")).strip().casefold() in {"nzb.life","nzb life","nzb.su","nzb su"}:
                match=row; break
        if match is None:
            rows.append({
                "name":"NZB.life",
                "url":DEV_NZBLIFE_API_URL,
                "api_key":DEV_NZBLIFE_API_KEY,
                "adult_categories":list(DEFAULT_ADULT_INDEXER_CATEGORIES),
                "enabled":True,
                "rss_enabled":True,
                "priority":15,
            })
        else:
            match["name"]="NZB.life"
            if not str(match.get("url") or "").strip() or "nzb.su" in str(match.get("url") or "").lower(): match["url"]=DEV_NZBLIFE_API_URL
            if not str(match.get("api_key") or "").strip(): match["api_key"]=DEV_NZBLIFE_API_KEY
            if not match.get("adult_categories"): match["adult_categories"]=list(DEFAULT_ADULT_INDEXER_CATEGORIES)
            match.setdefault("enabled",True); match.setdefault("rss_enabled",True); match.setdefault("priority",15)
        set_setting(db,"newznab_indexers_json",json.dumps(rows),commit=False)
        set_setting(db,"dev_nzblife_085_applied","true",commit=False)

    # Local-dev seed: ensure Usenet-Crawler is available once with the
    # requested development key. Explicit user edits/removal win afterward.
    uc_marker=db.get(AppSetting,"dev_usenet_crawler_085_applied")
    if uc_marker is None and DEV_USENET_CRAWLER_API_KEY:
        item=db.get(AppSetting,"newznab_indexers_json")
        try: rows=json.loads(item.value if item else "[]")
        except Exception: rows=[]
        match=None
        for row in rows:
            if str(row.get("name","")).strip().casefold() in {"usenet-crawler","usenet crawler","usenetcrawler"}:
                match=row; break
        if match is None:
            rows.append({
                "name":"Usenet-Crawler",
                "url":DEV_USENET_CRAWLER_API_URL,
                "api_key":DEV_USENET_CRAWLER_API_KEY,
                "adult_categories":list(DEFAULT_ADULT_INDEXER_CATEGORIES),
                "enabled":True,
                "rss_enabled":True,
                "priority":10,
            })
        else:
            match["name"]="Usenet-Crawler"
            if not str(match.get("url") or "").strip(): match["url"]=DEV_USENET_CRAWLER_API_URL
            if not str(match.get("api_key") or "").strip(): match["api_key"]=DEV_USENET_CRAWLER_API_KEY
            if not match.get("adult_categories"): match["adult_categories"]=list(DEFAULT_ADULT_INDEXER_CATEGORIES)
            match.setdefault("enabled",True); match.setdefault("rss_enabled",True); match.setdefault("priority",10)
        set_setting(db,"newznab_indexers_json",json.dumps(rows),commit=False)
        set_setting(db,"dev_usenet_crawler_085_applied","true",commit=False)

    # Local-dev seed: configure Astraweb once for the native ScarletX downloader.
    # After the marker exists, explicit provider edits/removal in Settings win.
    aw_marker=db.get(AppSetting,"dev_astraweb_091_applied")
    if aw_marker is None and DEV_ASTRAWEB_USERNAME and DEV_ASTRAWEB_PASSWORD:
        item=db.get(AppSetting,"native_usenet_providers_json")
        try: providers=json.loads(item.value if item else "[]")
        except Exception: providers=[]
        match=None
        for row in providers:
            if str(row.get("name","")).strip().casefold()=="astraweb" or str(row.get("host","")).strip().casefold() in {"us.astraweb.com","news.astraweb.com"}:
                match=row; break
        if match is None:
            providers.append({"name":"Astraweb","host":DEV_ASTRAWEB_HOST,"port":DEV_ASTRAWEB_PORT,"username":DEV_ASTRAWEB_USERNAME,"password":DEV_ASTRAWEB_PASSWORD,"use_ssl":True,"connections":DEV_ASTRAWEB_CONNECTIONS,"enabled":True,"priority":1})
        else:
            match["name"]="Astraweb"
            if not str(match.get("host") or "").strip(): match["host"]=DEV_ASTRAWEB_HOST
            if not int(match.get("port") or 0): match["port"]=DEV_ASTRAWEB_PORT
            if not str(match.get("username") or "").strip(): match["username"]=DEV_ASTRAWEB_USERNAME
            if not str(match.get("password") or "").strip(): match["password"]=DEV_ASTRAWEB_PASSWORD
            match["use_ssl"]=True; match["port"]=DEV_ASTRAWEB_PORT; match["connections"]=DEV_ASTRAWEB_CONNECTIONS; match.setdefault("enabled",True); match.setdefault("priority",1)
        set_setting(db,"native_usenet_providers_json",json.dumps(providers),commit=False)
        set_setting(db,"dev_astraweb_091_applied","true",commit=False)

    # ScarletX security policy: native NNTP is TLS-only. Sanitize retained provider
    # rows before runtime model validation, including older configurations that
    # may have allowed plaintext NNTP. Common plaintext ports are moved to 563.
    provider_item=db.get(AppSetting,"native_usenet_providers_json")
    try: secure_providers=json.loads(provider_item.value if provider_item else "[]")
    except Exception: secure_providers=[]
    secure_changed=False
    for row in secure_providers:
        if row.get("use_ssl") is not True:
            row["use_ssl"]=True; secure_changed=True
        try: port=int(row.get("port") or 563)
        except Exception: port=563
        if port in {23,25,80,119,3128}:
            row["port"]=563; secure_changed=True
    if secure_changed:
        set_setting(db,"native_usenet_providers_json",json.dumps(secure_providers),commit=False)

    # Local-dev seed: configure Newshosting once for the native downloader.
    # Explicit edits/removal win after the marker is created.
    nh_marker=db.get(AppSetting,"dev_newshosting_091_applied")
    if nh_marker is None and DEV_NEWSHOSTING_USERNAME and DEV_NEWSHOSTING_PASSWORD:
        item=db.get(AppSetting,"native_usenet_providers_json")
        try: providers=json.loads(item.value if item else "[]")
        except Exception: providers=[]
        match=None
        for row in providers:
            if str(row.get("name"," ")).strip().casefold()=="newshosting" or str(row.get("host"," ")).strip().casefold() in {"news.newshosting.com","news-us.newshosting.com"}:
                match=row; break
        if match is None:
            providers.append({"name":"Newshosting","host":DEV_NEWSHOSTING_HOST,"port":DEV_NEWSHOSTING_PORT,"username":DEV_NEWSHOSTING_USERNAME,"password":DEV_NEWSHOSTING_PASSWORD,"use_ssl":True,"connections":DEV_NEWSHOSTING_CONNECTIONS,"enabled":True,"priority":2})
        else:
            match["name"]="Newshosting"
            match["host"]=DEV_NEWSHOSTING_HOST
            match["port"]=DEV_NEWSHOSTING_PORT
            if not str(match.get("username") or "").strip(): match["username"]=DEV_NEWSHOSTING_USERNAME
            if not str(match.get("password") or "").strip(): match["password"]=DEV_NEWSHOSTING_PASSWORD
            match["use_ssl"]=True; match["connections"]=DEV_NEWSHOSTING_CONNECTIONS; match.setdefault("enabled",True); match.setdefault("priority",2)
        set_setting(db,"native_usenet_providers_json",json.dumps(providers),commit=False)
        set_setting(db,"dev_newshosting_091_applied","true",commit=False)

    # Performance-tuned working set. Provider values remain hard maxima; ScarletX
    # uses an adaptive 120-worker ceiling by default and learns the faster provider.
    perf_marker=db.get(AppSetting,"dev_native_perf_cap_032_applied")
    if perf_marker is None:
        cap_item=db.get(AppSetting,"native_usenet_max_connections")
        try: current_cap=int(cap_item.value if cap_item else 0)
        except Exception: current_cap=0
        if current_cap in {0, 20, 60, 150}:
            set_setting(db,"native_usenet_max_connections","120",commit=False)
        set_setting(db,"dev_native_perf_cap_032_applied","true",commit=False)

    retry_marker=db.get(AppSetting,"dev_native_retry_policy_033_applied")
    if retry_marker is None:
        retry_item=db.get(AppSetting,"native_usenet_max_retries")
        try: retry_count=int(retry_item.value if retry_item else 2)
        except Exception: retry_count=2
        # Older previews interpreted this value per-provider, so values such as 5
        # could create a retry storm. 0.3.3 treats it as a total transient budget.
        if retry_count > 2:
            set_setting(db,"native_usenet_max_retries","2",commit=False)
        set_setting(db,"dev_native_retry_policy_033_applied","true",commit=False)

    import_marker=db.get(AppSetting,"dev_native_auto_import_033_applied")
    if import_marker is None:
        # ScarletX's native Usenet flow is designed to finish as an organized scene,
        # not leave a completed payload directory for manual handling.
        set_setting(db,"file_management_enabled","true",commit=False)
        set_setting(db,"completed_download_import_enabled","true",commit=False)
        set_setting(db,"dev_native_auto_import_033_applied","true",commit=False)

    db.commit()
    invalidate_settings_cache(db)

def _int(v,k,d,m):
    try:return max(m,int(v[k]))
    except Exception:return d
def _float(v,k,d,m):
    try:return max(m,float(v[k]))
    except Exception:return d
def _bool(v,k,d):
    return str(v.get(k,str(d))).strip().lower() in {"1","true","yes","on"}

def load_database_settings(db, *, force=False):
    key=_cache_key(db); now=time.monotonic()
    if not force:
        with _SETTINGS_CACHE_LOCK:
            cached=_SETTINGS_CACHE.get(key)
            if cached and now-cached[0] < _SETTINGS_CACHE_TTL:
                return cached[1].model_copy(deep=True)
    d=Settings(); v=default_setting_values();v.update({x.key:x.value for x in db.query(AppSetting).all()})
    settings=Settings(
      app_name=v.get("app_name") or "ScarletX",theporndb_api_key=SecretStr(v.get("theporndb_api_key","")),theporndb_base_url=v.get("theporndb_base_url",d.theporndb_base_url),
      newznab_indexers_json=SecretStr(v.get("newznab_indexers_json","[]")),
      native_usenet_enabled=_bool(v,"native_usenet_enabled",True),native_usenet_providers_json=SecretStr(v.get("native_usenet_providers_json","[]")),
      native_usenet_incomplete_dir=v.get("native_usenet_incomplete_dir",d.native_usenet_incomplete_dir),native_usenet_complete_dir=v.get("native_usenet_complete_dir",d.native_usenet_complete_dir),
      native_usenet_max_connections=_int(v,"native_usenet_max_connections",60,1),native_usenet_max_retries=_int(v,"native_usenet_max_retries",2,0),native_usenet_speed_limit_mb_s=_float(v,"native_usenet_speed_limit_mb_s",0.0,0),
      native_usenet_repair_enabled=_bool(v,"native_usenet_repair_enabled",True),native_usenet_unpack_enabled=_bool(v,"native_usenet_unpack_enabled",True),
      completed_download_import_enabled=_bool(v,"completed_download_import_enabled",True),
      download_poll_seconds=_int(v,"download_poll_seconds",30,10),file_management_enabled=_bool(v,"file_management_enabled",False),scene_naming_template=v.get("scene_naming_template",d.scene_naming_template),
      automatic_search_enabled=_bool(v,"automatic_search_enabled",False),automatic_search_interval_minutes=_int(v,"automatic_search_interval_minutes",60,5),automatic_search_batch_size=_int(v,"automatic_search_batch_size",10,1),
      rss_sync_enabled=_bool(v,"rss_sync_enabled",False),rss_sync_interval_minutes=_int(v,"rss_sync_interval_minutes",15,5),rss_max_releases_per_indexer=_int(v,"rss_max_releases_per_indexer",100,10),rss_max_grabs_per_cycle=_int(v,"rss_max_grabs_per_cycle",10,1),
      import_mode=v.get("import_mode","move"),recycle_bin_path=v.get("recycle_bin_path",""),minimum_free_space_gb=_float(v,"minimum_free_space_gb",1.0,0),backup_enabled=_bool(v,"backup_enabled",True),backup_directory=v.get("backup_directory","./backups"),
      backup_interval_hours=_int(v,"backup_interval_hours",24,1),backup_keep=_int(v,"backup_keep",14,1),api_key_enabled=_bool(v,"api_key_enabled",False),api_key=SecretStr(v.get("api_key","")),scarletx_log_level=v.get("scarletx_log_level","INFO")
    )
    with _SETTINGS_CACHE_LOCK:
        _SETTINGS_CACHE[key]=(now,settings.model_copy(deep=True))
    return settings
