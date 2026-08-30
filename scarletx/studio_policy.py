from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

# ScarletX is intentionally studio-only. These are creator-upload, tube, clip-store,
# and live-cam platforms rather than production studios/sites. Keep this policy in
# one place so TPDB search, detail, performer scene lists, and studio search agree.
BLOCKED_PLATFORM_TOKENS = {
    "onlyfans", "only fans", "manyvids", "many vids", "pornhub", "porn hub",
    "fansly", "loyalfans", "loyal fans", "justforfans", "just for fans",
    "fancentro", "fan centro", "fanvue", "clips4sale", "clips 4 sale",
    "iwantclips", "i want clips", "apclips", "ap clips", "modelhub", "model hub",
    "chaturbate", "camsoda", "cam soda", "myfreecams", "my free cams",
    "streamate", "bongacams", "bonga cams", "stripchat", "cam4",
    "livejasmin", "live jasmin", "flirt4free", "flirt 4 free",
    "xhamster", "x hamster", "xvideos", "x videos", "youporn", "you porn",
    "redtube", "red tube", "spankbang", "eporner", "motherless",
    "mydirtyhobby", "my dirty hobby", "frisk", "unlockd", "patreon", "gumroad",
    "analvids", "anal vids", "anal vids network",
}

BLOCKED_PLATFORM_DOMAINS = {
    "onlyfans.com", "manyvids.com", "pornhub.com", "fansly.com",
    "loyalfans.com", "justfor.fans", "justforfans.app", "fancentro.com",
    "fanvue.com", "clips4sale.com", "iwantclips.com", "apclips.com",
    "modelhub.com", "chaturbate.com", "camsoda.com", "myfreecams.com",
    "streamate.com", "bongacams.com", "stripchat.com", "cam4.com",
    "livejasmin.com", "flirt4free.com", "xhamster.com", "xvideos.com",
    "youporn.com", "redtube.com", "spankbang.com", "eporner.com",
    "motherless.com", "mydirtyhobby.com", "frisk.chat", "unlockd.me",
    "patreon.com", "gumroad.com",
}

def _text(value: Any) -> str:
    return str(value or "").strip().lower()

def _host(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    try:
        host = (urlparse(text).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""
    return host

def _blocked_text(value: Any) -> bool:
    text = _text(value)
    return bool(text and any(token in text for token in BLOCKED_PLATFORM_TOKENS))

def _blocked_url(value: Any) -> bool:
    host = _host(value)
    if not host:
        return False
    return any(host == domain or host.endswith("." + domain) for domain in BLOCKED_PLATFORM_DOMAINS)

def is_allowed_tpdb_site_raw(site: dict[str, Any] | None) -> bool:
    if not isinstance(site, dict) or not site:
        return False
    name = site.get("name") or site.get("short_name")
    identifier = site.get("uuid") or site.get("id") or site.get("_id")
    # ScarletX only trusts a production site/studio that TPDB identifies as an
    # actual site entity. A loose name in scene metadata is not sufficient.
    if not identifier or not name or _text(name) in {"unknown", "n/a", "none"}:
        return False
    chain = [site]
    for key in ("parent", "network"):
        nested = site.get(key)
        if isinstance(nested, dict):
            chain.append(nested)
    for item in chain:
        if _blocked_text(item.get("name")) or _blocked_text(item.get("short_name")):
            return False
        if _blocked_url(item.get("url")):
            return False
    return True

def studio_only_reason_raw(scene: dict[str, Any]) -> str | None:
    site = scene.get("site")
    if not isinstance(site, dict) or not site:
        return "Scene has no TPDB studio/site"
    if not is_allowed_tpdb_site_raw(site):
        return f"Scene source is not an allowed studio: {site.get('name') or site.get('short_name') or 'unknown'}"
    if _blocked_url(scene.get("url")) or _blocked_text(scene.get("url")):
        return "Scene URL belongs to a creator/tube platform"
    return None

def is_allowed_tpdb_scene_raw(scene: dict[str, Any]) -> bool:
    return studio_only_reason_raw(scene) is None

def is_allowed_remote_scene(scene: Any) -> bool:
    studio = getattr(scene, "studio", None)
    if studio is None:
        return False
    name = getattr(studio, "name", None)
    url = getattr(studio, "url", None)
    source_url = getattr(scene, "source_url", None)
    if not name or _text(name) in {"unknown", "n/a", "none"}:
        return False
    return not (_blocked_text(name) or _blocked_url(url) or _blocked_url(source_url) or _blocked_text(source_url))
