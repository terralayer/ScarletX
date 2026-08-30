import json
import os
from pydantic import BaseModel, SecretStr

DEFAULT_ADULT_INDEXER_CATEGORIES = [6000, 6010, 6020, 6040]
DEV_NZBGEEK_API_KEY = os.getenv("SCARLETX_NZBGEEK_API_KEY", "")
DEV_NZBGEEK_API_URL = os.getenv("SCARLETX_NZBGEEK_API_URL", "https://api.nzbgeek.info/api")
DEV_TREASURE_MAPS_API_KEY = os.getenv("SCARLETX_TREASURE_MAPS_API_KEY", "")
DEV_TREASURE_MAPS_API_URL = os.getenv("SCARLETX_TREASURE_MAPS_API_URL", "https://treasure-maps.com/api")
DEV_NZBLIFE_API_KEY = os.getenv("SCARLETX_NZBLIFE_API_KEY", "")
DEV_NZBLIFE_API_URL = os.getenv("SCARLETX_NZBLIFE_API_URL", "https://api.nzb.life")
DEV_USENET_CRAWLER_API_KEY = os.getenv("SCARLETX_USENET_CRAWLER_API_KEY", "")
DEV_USENET_CRAWLER_API_URL = os.getenv("SCARLETX_USENET_CRAWLER_API_URL", "https://www.usenet-crawler.com/api")
DEV_ASTRAWEB_HOST = os.getenv("SCARLETX_ASTRAWEB_HOST", "us.astraweb.com")
DEV_ASTRAWEB_PORT = int(os.getenv("SCARLETX_ASTRAWEB_PORT", "563"))
DEV_ASTRAWEB_USERNAME = os.getenv("SCARLETX_ASTRAWEB_USERNAME", "")
DEV_ASTRAWEB_PASSWORD = os.getenv("SCARLETX_ASTRAWEB_PASSWORD", "")
DEV_ASTRAWEB_CONNECTIONS = int(os.getenv("SCARLETX_ASTRAWEB_CONNECTIONS", "50"))
DEV_NEWSHOSTING_HOST = os.getenv("SCARLETX_NEWSHOSTING_HOST", "news.newshosting.com")
DEV_NEWSHOSTING_PORT = int(os.getenv("SCARLETX_NEWSHOSTING_PORT", "563"))
DEV_NEWSHOSTING_USERNAME = os.getenv("SCARLETX_NEWSHOSTING_USERNAME", "")
DEV_NEWSHOSTING_PASSWORD = os.getenv("SCARLETX_NEWSHOSTING_PASSWORD", "")
DEV_NEWSHOSTING_CONNECTIONS = int(os.getenv("SCARLETX_NEWSHOSTING_CONNECTIONS", "100"))

def _default_indexers() -> str:
    raw = os.getenv("SCARLETX_NEWZNAB_INDEXERS_JSON", "")
    if raw.strip():
        return raw
    return json.dumps([
        {
            "name": "NZBGeek",
            "url": DEV_NZBGEEK_API_URL,
            "api_key": DEV_NZBGEEK_API_KEY,
            "adult_categories": list(DEFAULT_ADULT_INDEXER_CATEGORIES),
            "enabled": True,
            "rss_enabled": True,
            "priority": 25,
        },
        {
            "name": "Treasure Maps",
            "url": DEV_TREASURE_MAPS_API_URL,
            "api_key": DEV_TREASURE_MAPS_API_KEY,
            "adult_categories": list(DEFAULT_ADULT_INDEXER_CATEGORIES),
            "enabled": True,
            "rss_enabled": True,
            "priority": 20,
        },
        {
            "name": "NZB.life",
            "url": DEV_NZBLIFE_API_URL,
            "api_key": DEV_NZBLIFE_API_KEY,
            "adult_categories": list(DEFAULT_ADULT_INDEXER_CATEGORIES),
            "enabled": True,
            "rss_enabled": True,
            "priority": 15,
        },
        {
            "name": "Usenet-Crawler",
            "url": DEV_USENET_CRAWLER_API_URL,
            "api_key": DEV_USENET_CRAWLER_API_KEY,
            "adult_categories": list(DEFAULT_ADULT_INDEXER_CATEGORIES),
            "enabled": True,
            "rss_enabled": True,
            "priority": 10,
        }
    ])

class Settings(BaseModel):
    app_name: str = "ScarletX"
    theporndb_api_key: SecretStr = SecretStr(os.getenv("SCARLETX_TPDB_API_KEY", ""))
    theporndb_base_url: str = os.getenv("SCARLETX_TPDB_BASE_URL", "https://api.theporndb.net")
    newznab_indexers_json: SecretStr = SecretStr(_default_indexers())
    native_usenet_enabled: bool = os.getenv("SCARLETX_NATIVE_USENET_ENABLED", "true").strip().lower() not in {"0","false","no","off"}
    native_usenet_providers_json: SecretStr = SecretStr(os.getenv("SCARLETX_USENET_PROVIDERS_JSON", "[]"))
    native_usenet_incomplete_dir: str = os.getenv("SCARLETX_USENET_INCOMPLETE_DIR", "./downloads/incomplete")
    native_usenet_complete_dir: str = os.getenv("SCARLETX_USENET_COMPLETE_DIR", "./downloads/complete")
    native_usenet_max_connections: int = int(os.getenv("SCARLETX_USENET_MAX_CONNECTIONS", "120"))
    native_usenet_max_retries: int = int(os.getenv("SCARLETX_USENET_MAX_RETRIES", "2"))
    native_usenet_speed_limit_mb_s: float = float(os.getenv("SCARLETX_USENET_SPEED_LIMIT_MB_S", "0"))
    native_usenet_repair_enabled: bool = os.getenv("SCARLETX_USENET_REPAIR", "true").strip().lower() not in {"0","false","no","off"}
    native_usenet_unpack_enabled: bool = os.getenv("SCARLETX_USENET_UNPACK", "true").strip().lower() not in {"0","false","no","off"}
    completed_download_import_enabled: bool = True
    download_poll_seconds: int = 30
    file_management_enabled: bool = True
    scene_naming_template: str = "{Studio}/{Title} ({Year}) [{Quality}]"
    automatic_search_enabled: bool = False
    automatic_search_interval_minutes: int = 60
    automatic_search_batch_size: int = 10
    rss_sync_enabled: bool = False
    rss_sync_interval_minutes: int = 15
    rss_max_releases_per_indexer: int = 100
    rss_max_grabs_per_cycle: int = 10
    import_mode: str = "move"
    recycle_bin_path: str = ""
    minimum_free_space_gb: float = 1.0
    backup_enabled: bool = True
    backup_directory: str = "./backups"
    backup_interval_hours: int = 24
    backup_keep: int = 14
    api_key_enabled: bool = False
    api_key: SecretStr = SecretStr("")
    scarletx_log_level: str = "INFO"

    def native_usenet_providers(self):
        from .native_usenet import UsenetProviderConfig
        try:
            raw = json.loads(self.native_usenet_providers_json.get_secret_value() or "[]")
        except json.JSONDecodeError:
            raw = []
        return [UsenetProviderConfig.model_validate(item) for item in raw]


    def newznab_indexers(self):
        from .newznab import NewznabIndexer
        raw = json.loads(self.newznab_indexers_json.get_secret_value() or "[]")
        cleaned = []
        for item in raw:
            item = dict(item)
            # Old SceneCore fields are ignored; only adult Newznab categories remain.
            if not item.get("adult_categories"):
                item["adult_categories"] = item.get("categories") or list(DEFAULT_ADULT_INDEXER_CATEGORIES)
            for key in ("categories", "tv_categories", "movie_categories", "implementation"):
                item.pop(key, None)
            cleaned.append(item)
        return [NewznabIndexer.model_validate(item) for item in cleaned]
