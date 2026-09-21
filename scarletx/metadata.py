from __future__ import annotations
from .config import Settings
from .tpdb import ThePornDBClient, ThePornDBError
class MetadataProviderError(RuntimeError): pass
class DirectMetadataClient:
    def __init__(self,settings:Settings,*,fresh:bool=False):
        self.settings=settings
        self.fresh=fresh
    async def __aenter__(self): return self
    async def __aexit__(self,*_): return None
    def _tpdb(self):
        key=self.settings.theporndb_api_key.get_secret_value()
        if not key: raise MetadataProviderError("ThePornDB API key is not configured")
        options = {"fresh": True} if self.fresh else {}
        return ThePornDBClient(key,self.settings.theporndb_base_url,**options)
    async def _call(self,method,*args,**kwargs):
        try:
            async with self._tpdb() as client:return await getattr(client,method)(*args,**kwargs)
        except ThePornDBError as exc: raise MetadataProviderError(str(exc)) from exc
    async def search_scenes(self,*a,**k):return await self._call("search_scenes",*a,**k)
    async def get_scene(self,*a,**k):return await self._call("get_scene",*a,**k)
    async def search_performers(self,*a,**k):return await self._call("search_performers",*a,**k)
    async def get_performer(self,*a,**k):return await self._call("get_performer",*a,**k)
    async def get_performer_scenes(self,*a,**k):return await self._call("get_performer_scenes",*a,**k)
    async def search_studios(self,*a,**k):return await self._call("search_studios",*a,**k)
    async def get_studio(self,*a,**k):return await self._call("get_studio",*a,**k)
def metadata_client(settings,*,fresh=False):return DirectMetadataClient(settings,fresh=fresh)
def metadata_provider_status(settings):
    ready=bool(settings.theporndb_api_key.get_secret_value())
    return {"status":"ok" if ready else "warning","provider":"ThePornDB","provider_id":"tpdb","configured":ready,"tpdb_configured":ready}
