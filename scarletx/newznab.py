from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree
import asyncio
import hashlib
import threading

import httpx
from pydantic import BaseModel, Field, SecretStr

NEWZNAB_NS = "http://www.newznab.com/DTD/2010/feeds/attributes/"
_SHARED_HTTP_CLIENTS: dict[tuple[str, str], httpx.AsyncClient] = {}
_SHARED_HTTP_LOCK = threading.RLock()


def _shared_http_client(indexer: "NewznabIndexer") -> httpx.AsyncClient:
    secret = indexer.api_key.get_secret_value()
    key = (indexer.url.rstrip("/"), hashlib.sha256(secret.encode()).hexdigest()[:16])
    with _SHARED_HTTP_LOCK:
        client = _SHARED_HTTP_CLIENTS.get(key)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(
                base_url=indexer.url.rstrip("/"), timeout=30, trust_env=False,
                headers={"Accept": "application/xml", "User-Agent": "ScarletX/0.3.10-beta.1"},
                limits=httpx.Limits(max_connections=40, max_keepalive_connections=20, keepalive_expiry=45),
            )
            _SHARED_HTTP_CLIENTS[key] = client
        return client


async def close_shared_newznab_clients() -> None:
    with _SHARED_HTTP_LOCK:
        clients = list(_SHARED_HTTP_CLIENTS.values())
        _SHARED_HTTP_CLIENTS.clear()
    await asyncio.gather(*(c.aclose() for c in clients if not c.is_closed), return_exceptions=True)


class NewznabError(RuntimeError):
    pass


class NewznabIndexer(BaseModel):
    name: str
    url: str
    api_key: SecretStr
    adult_categories: list[int] = Field(default_factory=list)
    enabled: bool = True
    rss_enabled: bool = True
    priority: int = 25

    def categories_for(self, content_type: str | None = None) -> list[int]:
        return list(dict.fromkeys(self.adult_categories))


class NewznabRelease(BaseModel):
    guid: str
    title: str
    download_url: str | None = None
    published_at: datetime | None = None
    size: int | None = None
    grabs: int | None = None
    categories: list[int] = Field(default_factory=list)
    indexer: str
    protocol: str = "usenet"


def _integer(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def parse_releases(xml: str, indexer: str) -> list[NewznabRelease]:
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise NewznabError(f"{indexer} returned invalid XML") from exc
    error = root.find("error")
    if error is not None:
        raise NewznabError(f"{indexer} returned API error {error.get('code', 'unknown')}")
    releases: list[NewznabRelease] = []
    for item in root.findall("./channel/item"):
        attrs = {attr.get("name"): attr.get("value") for attr in item.findall(f"{{{NEWZNAB_NS}}}attr")}
        enclosure = item.find("enclosure")
        published_at = None
        try:
            if item.findtext("pubDate"):
                published_at = parsedate_to_datetime(item.findtext("pubDate"))
        except (TypeError, ValueError):
            pass
        categories = [_integer(node.text) for node in item.findall("category")]
        releases.append(NewznabRelease(
            guid=item.findtext("guid") or item.findtext("link") or item.findtext("title") or "",
            title=item.findtext("title") or "Untitled release",
            download_url=(enclosure.get("url") if enclosure is not None else None) or item.findtext("link"),
            published_at=published_at,
            size=_integer(attrs.get("size") or (enclosure.get("length") if enclosure is not None else None)),
            grabs=_integer(attrs.get("grabs")),
            categories=[value for value in categories if value is not None],
            indexer=indexer,
            protocol="usenet",
        ))
    return releases


class NewznabClient:
    def __init__(
        self,
        indexer: NewznabIndexer,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.indexer = indexer
        self._owns_client = transport is not None
        if self._owns_client:
            self.client = httpx.AsyncClient(
                base_url=indexer.url.rstrip("/"), timeout=30, transport=transport, trust_env=False,
                headers={"Accept": "application/xml", "User-Agent": "ScarletX/0.3.10-beta.1"},
            )
        else:
            self.client = _shared_http_client(indexer)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object):
        if self._owns_client and not self.client.is_closed:
            await self.client.aclose()

    async def _request(self, params: dict[str, str | int]) -> str:
        safe_params = {**params, "apikey": self.indexer.api_key.get_secret_value()}
        try:
            response = await self.client.get("", params=safe_params)
            response.raise_for_status()
            return response.text
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            message = f"{self.indexer.name} returned HTTP {status}" if status else f"{self.indexer.name} is unavailable"
            raise NewznabError(message) from exc

    async def caps(self) -> bool:
        xml = await self._request({"t": "caps"})
        try:
            return ElementTree.fromstring(xml).tag == "caps"
        except ElementTree.ParseError as exc:
            raise NewznabError(f"{self.indexer.name} returned invalid capabilities XML") from exc

    async def rss(self, limit: int = 100, offset: int = 0, content_type: str | None = None) -> list[NewznabRelease]:
        params: dict[str, str | int] = {
            "t": "search",
            "extended": 1,
            "limit": limit,
            "offset": offset,
        }
        categories = self.indexer.categories_for(content_type)
        if categories:
            params["cat"] = ",".join(str(value) for value in categories)
        releases = parse_releases(await self._request(params), self.indexer.name)
        return releases

    async def search(
        self,
        query: str,
        limit: int = 100,
        offset: int = 0,
        content_type: str | None = None,
    ) -> list[NewznabRelease]:
        params: dict[str, str | int] = {
            "t": "search",
            "q": query,
            "extended": 1,
            "limit": limit,
            "offset": offset,
        }
        categories = self.indexer.categories_for(content_type)
        if categories:
            params["cat"] = ",".join(str(value) for value in categories)
        releases = parse_releases(await self._request(params), self.indexer.name)
        return releases
