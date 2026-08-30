import asyncio
import hashlib
import json
import os
import time
import threading
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from .studio_policy import is_allowed_tpdb_scene_raw, is_allowed_tpdb_site_raw, studio_only_reason_raw
from .schemas import (
    PerformerSearchResponse,
    RemotePerson,
    RemoteScene,
    RemoteStudio,
    RemoteTag,
    SearchResponse,
    StudioSearchResponse,
)



TPDB_CACHE_ROOT = Path(os.getenv("SCARLETX_CACHE_DIR", "./cache")).expanduser() / "tpdb" / "json"
_SHARED_HTTP_CLIENTS: dict[tuple[str, str], httpx.AsyncClient] = {}
_SHARED_HTTP_LOCK = threading.RLock()


def _shared_http_client(base_url: str, api_key: str) -> httpx.AsyncClient:
    key = (base_url.rstrip("/"), hashlib.sha256(api_key.encode()).hexdigest()[:16])
    with _SHARED_HTTP_LOCK:
        client = _SHARED_HTTP_CLIENTS.get(key)
        if client is None or client.is_closed:
            headers = {"Accept": "application/json", "User-Agent": "ScarletX/0.3.6"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            client = httpx.AsyncClient(
                base_url=base_url.rstrip("/"), headers=headers, timeout=20,
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=20, keepalive_expiry=45),
            )
            _SHARED_HTTP_CLIENTS[key] = client
        return client


async def close_shared_tpdb_clients() -> None:
    with _SHARED_HTTP_LOCK:
        clients = list(_SHARED_HTTP_CLIENTS.values())
        _SHARED_HTTP_CLIENTS.clear()
    await asyncio.gather(*(c.aclose() for c in clients if not c.is_closed), return_exceptions=True)


def _cache_key(path: str, params: dict | None) -> Path:
    payload = json.dumps({"path": path, "params": params or {}}, sort_keys=True, separators=(",", ":"))
    return TPDB_CACHE_ROOT / f"{hashlib.sha256(payload.encode()).hexdigest()}.json"


def _read_cache(path: Path, max_age: int | None = None):
    try:
        if not path.exists():
            return None
        if max_age is not None and time.time() - path.stat().st_mtime > max_age:
            return None
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, separators=(",", ":")))
        temp.replace(path)
    except OSError:
        pass


class ThePornDBError(RuntimeError):
    pass


class StudioOnlySceneError(ThePornDBError):
    pass


def _id(value: Any) -> str:
    return str(value or "")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def normalize_scene(raw: dict[str, Any]) -> RemoteScene:
    site = raw.get("site") or {}
    performers = raw.get("performers") or []
    tags = raw.get("tags") or []
    parsed_date = _parse_date(raw.get("date"))
    studio = None
    if site:
        studio = RemoteStudio(
            id=_id(site.get("uuid") or site.get("id")), name=_text(site.get("name")) or "Unknown",
            search_id=_int_or_none(site.get("id") if site.get("id") is not None else site.get("_id")),
            url=_text(site.get("url")), logo_url=_text(site.get("logo") or site.get("favicon")),
            poster_url=_text(site.get("poster")), description=_text(site.get("description")),
        )
    return RemoteScene(
        id=_id(raw.get("id") or raw.get("uuid") or raw.get("_id")),
        title=_text(raw.get("title")) or "Untitled", description=_text(raw.get("description")),
        release_date=parsed_date, duration=_int_or_none(raw.get("duration")), source_url=_text(raw.get("url")),
        image_url=_text(raw.get("image")), back_image_url=_text(raw.get("back_image")),
        poster_url=_text(raw.get("poster") or raw.get("poster_image")), studio=studio,
        performers=[normalize_performer(p) for p in performers],
        tags=[RemoteTag(id=_id(t.get("uuid") or t.get("id")), name=_text(t.get("name")) or "Unknown") for t in tags if isinstance(t, dict)],
    )


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _age_on(birthday: date | None, end: date | None = None) -> int | None:
    if birthday is None:
        return None
    end = end or date.today()
    return end.year - birthday.year - ((end.month, end.day) < (birthday.month, birthday.day))


def _performer_status(deathday: date | None, career_start_year: int | None, career_end_year: int | None) -> str | None:
    if deathday is not None:
        return "Deceased"
    if career_end_year:
        return "Retired"
    if career_start_year:
        return "Active"
    return None


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "fake", "enhanced"}:
            return True
        if normalized in {"false", "no", "0", "real", "natural"}:
            return False
    return None


def normalize_performer(raw: dict[str, Any]) -> RemotePerson:
    # Scene credits are PerformerSite resources. Prefer their canonical parent
    # performer so clicking a scene credit always opens the real performer page.
    source = raw.get("parent") or raw
    aliases = source.get("aliases") or []
    extras = source.get("extras") or source.get("extra") or {}
    birthday = _parse_date(extras.get("birthday") or source.get("birthday"))
    deathday = _parse_date(extras.get("deathday") or source.get("deathday"))
    links = extras.get("links") or {}
    career_start_year = _int_or_none(extras.get("career_start_year"))
    career_end_year = _int_or_none(extras.get("career_end_year"))
    if not isinstance(links, dict):
        links = {}
    return RemotePerson(
        id=_id(source.get("id") or source.get("_id")),
        search_id=source.get("_id"),
        name=_text(source.get("name") or source.get("full_name")) or "Unknown",
        image_url=_text(source.get("image") or source.get("thumbnail") or source.get("face")),
        bio=_text(source.get("bio")),
        aliases=[str(alias) for alias in aliases if alias],
        gender=_text(extras.get("gender")),
        birthday=birthday,
        deathday=deathday,
        age=_age_on(birthday, deathday),
        birthplace=_text(extras.get("birthplace")),
        birthplace_code=_text(extras.get("birthplace_code")),
        nationality=_text(extras.get("nationality")),
        ethnicity=_text(extras.get("ethnicity")),
        measurements=_text(extras.get("measurements")),
        cup_size=_text(extras.get("cupsize") or extras.get("cup_size")),
        fake_boobs=_optional_bool(extras.get("fake_boobs", extras.get("fakeboobs"))),
        waist=_text(extras.get("waist")),
        hips=_text(extras.get("hips")),
        same_sex_only=_optional_bool(extras.get("same_sex_only")),
        status=_performer_status(deathday, career_start_year, career_end_year),
        height=_text(extras.get("height")),
        weight=_text(extras.get("weight")),
        hair_color=_text(extras.get("hair_colour") or extras.get("haircolor") or extras.get("hair_color")),
        eye_color=_text(extras.get("eye_colour") or extras.get("eyecolor") or extras.get("eye_color")),
        tattoos=_text(extras.get("tattoos")),
        piercings=_text(extras.get("piercings")),
        astrology=_text(extras.get("astrology")),
        career_start_year=career_start_year,
        career_end_year=career_end_year,
        links={str(k): (str(v) if v is not None else None) for k, v in links.items()},
    )


def normalize_studio(raw: dict[str, Any]) -> RemoteStudio:
    return RemoteStudio(
        id=_id(raw.get("uuid") or raw.get("id")),
        search_id=_int_or_none(raw.get("id") if raw.get("id") is not None else raw.get("_id")),
        name=_text(raw.get("name") or raw.get("short_name")) or "Unknown",
        url=_text(raw.get("url")), logo_url=_text(raw.get("logo") or raw.get("favicon")),
        poster_url=_text(raw.get("poster")), description=_text(raw.get("description")),
    )


class ThePornDBClient:
    def __init__(self, api_key: str, base_url: str = "https://api.theporndb.net", transport: httpx.AsyncBaseTransport | None = None, max_retries: int = 3):
        self.max_retries = max_retries
        self._owns_client = transport is not None
        if self._owns_client:
            headers = {"Accept": "application/json", "User-Agent": "ScarletX/0.3.6"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            self.client = httpx.AsyncClient(base_url=base_url.rstrip("/"), headers=headers, timeout=20, transport=transport)
        else:
            self.client = _shared_http_client(base_url, api_key)

    async def __aenter__(self): return self
    async def __aexit__(self, *_): await self.aclose()
    async def aclose(self):
        if self._owns_client and not self.client.is_closed:
            await self.client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        cache_path = _cache_key(path, params)
        # Search pages change more often than entity details. Both are persistent
        # and stale cache is used as an offline/TPDB-outage fallback.
        ttl = 300 if params else 86400
        cached = _read_cache(cache_path, ttl)
        if cached is not None:
            return cached
        stale = _read_cache(cache_path, None)
        last_error = None
        for attempt in range(min(self.max_retries, 2)):
            try:
                response = await self.client.get(path, params=params)
                if (response.status_code == 429 or response.status_code >= 500) and attempt + 1 < min(self.max_retries, 2):
                    await asyncio.sleep(0.35 * (attempt + 1)); continue
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict):
                    _write_cache(cache_path, payload)
                return payload
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt + 1 < min(self.max_retries, 2):
                    await asyncio.sleep(0.35 * (attempt + 1))
            except httpx.HTTPStatusError as exc:
                # Do not hide authorization/not-found errors behind stale cache.
                if exc.response.status_code not in {429, 500, 502, 503, 504}:
                    raise ThePornDBError(f"ThePornDB returned HTTP {exc.response.status_code}") from exc
                last_error = exc
        if stale is not None:
            return stale
        raise ThePornDBError("ThePornDB is unavailable") from last_error

    async def search_scenes(
        self,
        query: str | None = None,
        page: int = 1,
        per_page: int = 24,
        performer_id: str | None = None,
        site_id: str | None = None,
    ) -> SearchResponse:
        params: dict[str, str | int] = {"page": page, "per_page": per_page}
        if query:
            params["q"] = query
        if performer_id:
            params["performer_id"] = performer_id
        if site_id:
            params["site_id"] = site_id
        payload = await self._get("/scenes", params)
        meta = payload.get("meta") or {}
        allowed = [x for x in payload.get("data", []) if is_allowed_tpdb_scene_raw(x)]
        return SearchResponse(items=[normalize_scene(x) for x in allowed], total=meta.get("total", 0), page=meta.get("current_page", page), per_page=meta.get("per_page", per_page))

    async def get_scene(self, identifier: str) -> RemoteScene:
        payload = await self._get(f"/scenes/{identifier}")
        raw = payload["data"]
        reason = studio_only_reason_raw(raw)
        if reason:
            raise StudioOnlySceneError(reason)
        return normalize_scene(raw)

    async def search_performers(self, query: str, page: int = 1, per_page: int = 24) -> PerformerSearchResponse:
        payload = await self._get("/performers", {"q": query, "page": page, "per_page": per_page})
        meta = payload.get("meta") or {}
        return PerformerSearchResponse(items=[normalize_performer(x) for x in payload.get("data", [])], total=meta.get("total", 0), page=meta.get("current_page", page), per_page=meta.get("per_page", per_page))

    async def get_performer(self, identifier: str) -> RemotePerson:
        payload = await self._get(f"/performers/{identifier}")
        return normalize_performer(payload["data"])

    async def get_performer_scenes(self, identifier: str, page: int = 1, per_page: int = 48) -> SearchResponse:
        payload = await self._get(f"/performers/{identifier}/scenes", {"page": page, "per_page": per_page})
        meta = payload.get("meta") or {}
        items = [normalize_scene(x) for x in payload.get("data", []) if is_allowed_tpdb_scene_raw(x)]
        return SearchResponse(
            items=items,
            total=meta.get("total", len(items)),
            page=meta.get("current_page", page),
            per_page=meta.get("per_page", per_page),
        )

    async def search_studios(self, query: str, page: int = 1, per_page: int = 24) -> StudioSearchResponse:
        payload = await self._get("/sites", {"q": query, "page": page, "per_page": per_page})
        meta = payload.get("meta") or {}
        allowed = [x for x in payload.get("data", []) if is_allowed_tpdb_site_raw(x)]
        return StudioSearchResponse(items=[normalize_studio(x) for x in allowed], total=meta.get("total", 0), page=meta.get("current_page", page), per_page=meta.get("per_page", per_page))

    async def get_studio(self, identifier: str) -> RemoteStudio:
        payload = await self._get(f"/sites/{identifier}")
        raw = payload["data"]
        if not is_allowed_tpdb_site_raw(raw):
            raise StudioOnlySceneError("ScarletX only manages production studio/sites")
        return normalize_studio(raw)
