import asyncio
import time
from datetime import date

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from scarletx.config import Settings
from scarletx.db import Base
from scarletx.models import Performer, Studio
from scarletx.routes import application
from scarletx import performer_search, studio_search
from scarletx.schemas import ImportRequest, PerformerSearchResponse, RemotePerson, RemoteStudio, StudioSearchResponse
from scarletx.performer_search import cache_performer_search, cache_performer_search_page
from scarletx.studio_search import cache_studio_search_page


@pytest.fixture
def factory(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path / "search.db"}',
                          connect_args={'check_same_thread': False},
                          pool_size=1, max_overflow=0, pool_timeout=.3)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(application, 'SessionLocal', sessions)
    monkeypatch.setattr(performer_search, 'SEARCH_CACHE_ROOT', tmp_path / 'performer-queries', raising=False)
    monkeypatch.setattr(studio_search, 'SEARCH_CACHE_ROOT', tmp_path / 'queries', raising=False)
    yield sessions
    engine.dispose()


class SearchProvider:
    def __init__(self):
        self.calls = []

    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass

    async def search_performers(self, query, page=1):
        self.calls.append(query)
        return PerformerSearchResponse(items=[RemotePerson(
            id='new-person', name='New Person', image_url='https://example.test/person.jpg',
            aliases=['Stage Name'], bio='Biography',
        )], total=1, page=page, per_page=24)

    async def get_performer(self, identifier):
        self.calls.append(('performer', identifier))
        return RemotePerson(id=identifier, name='New Person', image_url='https://example.test/person.jpg')

    async def search_studios(self, query, page=1):
        self.calls.append(query)
        return StudioSearchResponse(items=[RemoteStudio(
            id='new-studio', name='New Studio', logo_url='https://example.test/studio.png',
        )], total=1, page=page, per_page=24)

    async def get_studio(self, identifier):
        self.calls.append(('studio', identifier))
        return RemoteStudio(id=identifier, name='New Studio', logo_url='https://example.test/studio.png')


@pytest.mark.asyncio
async def test_external_performer_search_is_saved_and_repeat_search_is_local(factory, monkeypatch):
    provider = SearchProvider()
    monkeypatch.setattr(application, 'client', lambda _: provider)
    result = await application.search_performers('New Person', page=1, settings=Settings())
    assert result.items[0].id == 'new-person'
    with factory() as db:
        person = db.scalar(select(Performer).where(Performer.tpdb_id == 'new-person'))
        assert person is not None, 'external search results must be saved before image requests start'
        assert person.is_library is True
        assert person.monitored is False
        assert person.image_url == 'https://example.test/person.jpg'
    for query in ['new person', 'Stage Name']:
        cached = await application.search_performers(query, page=1, settings=Settings())
        assert cached.items[0].id == 'new-person'
    assert provider.calls == ['New Person']


@pytest.mark.asyncio
async def test_local_performer_search_does_not_contact_provider(factory, monkeypatch):
    with factory() as db:
        db.add(Performer(tpdb_id='saved', name='Saved Person', aliases='Known Alias',
                         monitored=True, is_library=True))
        db.commit()
    def unexpected_provider(_):
        raise AssertionError('local result must not wait for external metadata')
    monkeypatch.setattr(application, 'client', unexpected_provider)
    result = await application.search_performers('Known Alias', page=1, settings=Settings())
    assert [item.id for item in result.items] == ['saved']


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['performer', 'studio'])
async def test_explicit_local_search_never_contacts_provider_when_empty(factory, monkeypatch, kind):
    def unexpected_provider(_):
        raise AssertionError('source=local must never create an external provider')
    monkeypatch.setattr(application, 'client', unexpected_provider)
    route = application.search_performers if kind == 'performer' else application.search_studios

    result = await route('Missing Entity', page=1, settings=Settings(), source='local')

    assert result.items == []
    assert result.total == 0
    assert result.page == 1
    assert result.per_page == 24


@pytest.mark.asyncio
async def test_online_performer_search_bypasses_partial_local_results_and_caches_provider_pages(factory, monkeypatch):
    with factory() as db:
        db.add(Performer(tpdb_id='partial', name='Paged Performer Local', is_library=True))
        db.commit()

    class PagedProvider(SearchProvider):
        async def search_performers(self, query, page=1):
            self.calls.append(page)
            items = [
                RemotePerson(id=f'person-{page}-b', name=f'Paged Performer {page} B'),
                RemotePerson(id=f'person-{page}-a', name=f'Paged Performer {page} A'),
            ]
            return PerformerSearchResponse(items=items, total=50, page=page, per_page=24)

    provider = PagedProvider()
    monkeypatch.setattr(application, 'client', lambda _: provider)

    first = await application.search_performers(
        'Paged Performer', page=1, settings=Settings(), source='online',
    )
    repeated = await application.search_performers(
        'paged performer', page=1, settings=Settings(), source='online',
    )
    second = await application.search_performers(
        'Paged Performer', page=2, settings=Settings(), source='online',
    )
    repeated_second = await application.search_performers(
        'Paged Performer', page=2, settings=Settings(), source='online',
    )

    assert [item.id for item in first.items] == ['person-1-b', 'person-1-a']
    assert [item.id for item in second.items] == ['person-2-b', 'person-2-a']
    assert repeated == first
    assert repeated_second == second
    assert first.total == second.total == 50
    assert provider.calls == [1, 2]
    with factory() as db:
        assert db.scalar(select(Performer).where(Performer.tpdb_id == 'person-1-b')) is not None
        assert db.scalar(select(Performer).where(Performer.tpdb_id == 'person-2-a')) is not None
    assert list(performer_search.SEARCH_CACHE_ROOT.glob('*.json'))


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['performer', 'studio'])
async def test_saved_online_page_repersists_entities_without_provider(factory, monkeypatch, kind):
    settings = Settings()
    if kind == 'performer':
        expected_id = 'cached-person'
        result = PerformerSearchResponse(
            items=[RemotePerson(id=expected_id, name='Cached Person')],
            total=1, page=1, per_page=24,
        )
        cache_performer_search_page(settings, 'Cached Entity', result)
        route = application.search_performers
        model = Performer
    else:
        expected_id = 'cached-studio'
        result = StudioSearchResponse(
            items=[RemoteStudio(id=expected_id, name='Cached Studio')],
            total=1, page=1, per_page=24,
        )
        cache_studio_search_page(settings, 'Cached Entity', result)
        route = application.search_studios
        model = Studio

    def unexpected_provider(_):
        raise AssertionError('a saved provider page must be usable without the provider')
    monkeypatch.setattr(application, 'client', unexpected_provider)

    cached = await route('Cached Entity', page=1, settings=settings, source='online')

    assert cached == result
    with factory() as db:
        row = db.scalar(select(model).where(model.tpdb_id == expected_id))
        assert row is not None
        assert row.is_library is True
        assert row.monitored is False


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['performer', 'studio'])
async def test_failed_online_search_is_not_cached_and_can_be_retried(factory, monkeypatch, kind):
    class FlakyProvider(SearchProvider):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        async def _result(self, page, response_type, item):
            self.attempts += 1
            if self.attempts == 1:
                from scarletx.metadata import MetadataProviderError
                raise MetadataProviderError('temporary provider failure')
            return response_type(items=[item], total=1, page=page, per_page=24)

        async def search_performers(self, query, page=1):
            return await self._result(page, PerformerSearchResponse,
                                      RemotePerson(id='retry-person', name='Retry Person'))

        async def search_studios(self, query, page=1):
            return await self._result(page, StudioSearchResponse,
                                      RemoteStudio(id='retry-studio', name='Retry Studio'))

    provider = FlakyProvider()
    monkeypatch.setattr(application, 'client', lambda _: provider)
    route = application.search_performers if kind == 'performer' else application.search_studios

    with pytest.raises(HTTPException, match='temporary provider failure'):
        await route('Retry Entity', page=1, settings=Settings(), source='online')
    succeeded = await route('Retry Entity', page=1, settings=Settings(), source='online')
    cached = await route('Retry Entity', page=1, settings=Settings(), source='online')

    assert succeeded == cached
    assert provider.attempts == 2


def test_search_summaries_preserve_richer_details_and_existing_monitoring(factory):
    with factory() as db:
        db.add(Performer(tpdb_id='saved', name='Saved Person', bio='Complete biography',
                         aliases='Original Alias', monitored=True, is_library=True))
        db.commit()
    cache_performer_search(factory, [RemotePerson(id='saved', name='Saved Person',
                           image_url='https://example.test/image.jpg')])
    with factory() as db:
        person = db.scalar(select(Performer).where(Performer.tpdb_id == 'saved'))
        assert person.monitored is True
        assert person.bio == 'Complete biography'
        assert person.aliases == 'Original Alias'
        assert person.image_url == 'https://example.test/image.jpg'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['performer', 'studio'])
async def test_profile_artwork_releases_database_before_downloading(factory, monkeypatch, kind):
    engine = factory.kw['bind']
    with factory() as db:
        if kind == 'performer':
            db.add(Performer(tpdb_id='image-owner', name='Image Owner', image_url='https://example.test/image.jpg'))
        else:
            db.add(Studio(tpdb_id='image-owner', name='Image Owner', logo_url='https://example.test/image.jpg'))
        db.commit()
    async def thumbnail(*args, **kwargs):
        assert engine.pool.checkedout() == 0, 'image downloads must not reserve a library connection'
        return b'image', 'image/webp'
    monkeypatch.setattr(application, 'cached_remote_thumbnail', thumbnail)
    route = application.performer_artwork if kind == 'performer' else application.studio_artwork
    with factory() as db:
        result = await route('image-owner', size='card', db=db, settings=Settings())
    assert result.body == b'image'


@pytest.mark.asyncio
async def test_slow_artwork_database_read_does_not_freeze_other_requests(factory, monkeypatch):
    engine = factory.kw['bind']
    with factory() as db:
        db.add(Performer(tpdb_id='person', name='Person', image_url='https://example.test/image.jpg'))
        db.commit()
    async def thumbnail(*args, **kwargs): return b'image', 'image/webp'
    monkeypatch.setattr(application, 'cached_remote_thumbnail', thumbnail)
    def slow_read(*_): time.sleep(.15)
    event.listen(engine, 'before_cursor_execute', slow_read)
    try:
        with factory() as db:
            started = time.monotonic()
            task = asyncio.create_task(application.performer_artwork('person', size='card', db=db, settings=Settings()))
            await asyncio.sleep(.02)
            elapsed = time.monotonic() - started
            await task
        assert elapsed < .1, f'Artwork blocked other requests for {elapsed:.3f}s'
    finally:
        event.remove(engine, 'before_cursor_execute', slow_read)


@pytest.mark.asyncio
async def test_add_and_monitor_enables_monitoring_for_cached_search_result(factory, monkeypatch):
    with factory() as db:
        db.add(Performer(tpdb_id='new-person', name='New Person', is_library=True, monitored=False))
        db.commit()
    monkeypatch.setattr(application, 'client', lambda _: SearchProvider())
    monkeypatch.setattr(application, '_queue_adult_entity_hydration', lambda *args, **kwargs: 42)
    with factory() as db:
        result = await application.import_performer('new-person', ImportRequest(monitored=True), BackgroundTasks(), db, Settings())
        assert result['monitored'] is True


@pytest.mark.asyncio
async def test_external_studio_search_is_saved_and_reused(factory, monkeypatch):
    provider = SearchProvider()
    monkeypatch.setattr(application, 'client', lambda _: provider)
    result = await application.search_studios('New Studio', page=1, settings=Settings())
    assert result.items[0].id == 'new-studio'
    with factory() as db:
        studio = db.scalar(select(Studio).where(Studio.tpdb_id == 'new-studio'))
        assert studio is not None, 'studio search results must be saved before artwork requests start'
        assert studio.monitored is False
        assert studio.is_library is True
        assert studio.logo_url == 'https://example.test/studio.png'
    cached = await application.search_studios('new studio', page=1, settings=Settings())
    assert cached.items[0].id == 'new-studio'
    assert provider.calls == ['New Studio']


@pytest.mark.asyncio
async def test_local_studio_search_excludes_blocked_sources_and_paginates(factory, monkeypatch):
    with factory() as db:
        db.add_all([Studio(tpdb_id=f'studio-{i}', name=f'Saved Studio {i:02}', is_library=True)
                    for i in range(25)])
        db.add(Studio(tpdb_id='blocked', name='Saved Studio YourVids', is_library=True))
        db.commit()
    def unexpected_provider(_):
        raise AssertionError('local studio results must not wait for external metadata')
    monkeypatch.setattr(application, 'client', unexpected_provider)
    first = await application.search_studios('Saved Studio', page=1, settings=Settings())
    second = await application.search_studios('Saved Studio', page=2, settings=Settings())
    assert first.total == second.total == 25
    assert len(first.items) == 24
    assert [item.id for item in second.items] == ['studio-24']
    assert 'blocked' not in [item.id for item in first.items]


@pytest.mark.asyncio
async def test_studio_search_fetches_uncached_external_pages(factory, monkeypatch):
    class PagedProvider(SearchProvider):
        async def search_studios(self, query, page=1):
            self.calls.append(page)
            return StudioSearchResponse(items=[RemoteStudio(id=f'site-{i}', name=f'Paged Studio {i:02}')
                                               for i in range((page - 1) * 24, page * 24)],
                                        total=48, page=page, per_page=24)
    provider = PagedProvider()
    monkeypatch.setattr(application, 'client', lambda _: provider)
    with factory() as db:
        db.add(Studio(tpdb_id='partial-page', name='Paged Studio 99', is_library=True))
        db.commit()
    first = await application.search_studios('Paged Studio', page=1, settings=Settings(), source='online')
    repeat = await application.search_studios('Paged Studio', page=1, settings=Settings(), source='online')
    assert repeat.total == first.total == 48, 'saved first page must still advertise uncached later pages'
    assert [item.id for item in repeat.items] == [item.id for item in first.items]
    second = await application.search_studios('Paged Studio', page=2, settings=Settings(), source='online')
    assert len(first.items) == len(second.items) == 24
    assert set(item.id for item in first.items).isdisjoint(item.id for item in second.items)
    assert provider.calls == [1, 2]
    again = await application.search_studios('Paged Studio', page=2, settings=Settings(), source='online')
    assert again == second
    assert provider.calls == [1, 2]
    assert list(studio_search.SEARCH_CACHE_ROOT.glob('*.json')), 'query pagination must survive restarts'


@pytest.mark.asyncio
async def test_cached_performer_details_keep_computed_age(factory, monkeypatch):
    with factory() as db:
        db.add(Performer(tpdb_id='age-detail', name='Saved Detail', birthday=date(1980, 4, 20),
                         deathday=date(2020, 4, 19), is_library=True))
        db.commit()
    with factory() as db:
        result = await application.performer_detail('age-detail', db=db, settings=Settings())
    assert result.age == 39


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['performer', 'studio'])
async def test_saved_metadata_details_never_contact_provider(factory, monkeypatch, kind):
    model = Performer if kind == 'performer' else Studio
    with factory() as db:
        db.add(model(tpdb_id='saved-detail', name='Saved Detail', monitored=True, is_library=True))
        db.commit()
    def unexpected_provider(_):
        raise AssertionError('saved metadata details must load locally')
    monkeypatch.setattr(application, 'client', unexpected_provider)
    route = application.performer_detail if kind == 'performer' else application.studio_detail
    with factory() as db:
        result = await route('saved-detail', db=db, settings=Settings())
        assert result.id == 'saved-detail'
        assert result.name == 'Saved Detail'
        assert db.scalar(select(model)).monitored is True


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['performer', 'studio'])
async def test_cached_scene_credit_can_be_opened_as_a_library_profile(factory, monkeypatch, kind):
    model = Performer if kind == 'performer' else Studio
    with factory() as db:
        db.add(model(tpdb_id='scene-credit', name='Scene Credit', monitored=False, is_library=False))
        db.commit()
    def unexpected_provider(_):
        raise AssertionError('cached scene credits must not need a provider lookup')
    monkeypatch.setattr(application, 'client', unexpected_provider)
    route = application.performer_detail if kind == 'performer' else application.studio_detail
    library_route = (application.performer_library_detail_by_tpdb if kind == 'performer'
                     else application.studio_library_detail_by_tpdb)
    with factory() as db:
        await route('scene-credit', db=db, settings=Settings())
        result = library_route('scene-credit', db=db)
        assert result['tpdb_id'] == 'scene-credit'
        assert result['monitored'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['performer', 'studio'])
async def test_missing_metadata_details_are_fetched_once_and_saved(factory, monkeypatch, kind):
    provider = SearchProvider()
    monkeypatch.setattr(application, 'client', lambda _: provider)
    route = application.performer_detail if kind == 'performer' else application.studio_detail
    model = Performer if kind == 'performer' else Studio
    for _ in range(2):
        with factory() as db:
            result = await route('new-detail', db=db, settings=Settings())
            assert result.id == 'new-detail'
    assert provider.calls == [(kind, 'new-detail')]
    with factory() as db:
        row = db.scalar(select(model))
        assert row.is_library is True
        assert row.monitored is False


@pytest.mark.asyncio
async def test_add_and_monitor_enables_monitoring_for_cached_studio(factory, monkeypatch):
    with factory() as db:
        db.add(Studio(tpdb_id='new-studio', name='New Studio', is_library=True, monitored=False))
        db.commit()
    monkeypatch.setattr(application, 'client', lambda _: SearchProvider())
    monkeypatch.setattr(application, '_queue_adult_entity_hydration', lambda *args, **kwargs: 42)
    with factory() as db:
        result = await application.import_studio('new-studio', ImportRequest(monitored=True), BackgroundTasks(), db, Settings())
        assert result['monitored'] is True


@pytest.mark.asyncio
async def test_studio_search_summaries_preserve_richer_metadata_and_monitoring(factory, monkeypatch):
    with factory() as db:
        db.add(Studio(tpdb_id='new-studio', name='New Studio', description='Full description',
                      url='https://example.test', monitored=True, is_library=True))
        db.commit()
    monkeypatch.setattr(application, 'client', lambda _: SearchProvider())
    await application.search_studios('alternate search', page=1, settings=Settings())
    with factory() as db:
        row = db.scalar(select(Studio))
        assert row.description == 'Full description'
        assert row.url == 'https://example.test'
        assert row.monitored is True
        assert row.logo_url == 'https://example.test/studio.png'


@pytest.mark.asyncio
async def test_external_studio_artwork_metadata_is_saved_before_download(factory, monkeypatch):
    monkeypatch.setattr(application, 'client', lambda _: SearchProvider())
    monkeypatch.setattr(application, 'cached_studio_artwork', lambda _: None)
    monkeypatch.setattr(application, 'legacy_studio_artwork', lambda _: None)
    monkeypatch.setattr(application, 'cache_studio_artwork', lambda *_: None)
    async def download(*args, **kwargs):
        assert factory.kw['bind'].pool.checkedout() == 0
        with factory() as db:
            row = db.scalar(select(Studio).where(Studio.tpdb_id == 'art-studio'))
            assert row is not None, 'metadata fetched for studio artwork must also be saved'
            assert row.monitored is False
        return b'image'
    monkeypatch.setattr(application, 'download_and_prepare_studio_artwork', download)
    with factory() as db:
        result = await application.studio_artwork('art-studio', size='full', db=db, settings=Settings())
    assert result.body == b'image'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['performer', 'studio'])
async def test_slow_metadata_detail_read_does_not_block_other_requests(factory, monkeypatch, kind):
    engine = factory.kw['bind']
    model = Performer if kind == 'performer' else Studio
    with factory() as db:
        db.add(model(tpdb_id='slow-detail', name='Saved Detail', is_library=True))
        db.commit()
    monkeypatch.setattr(application, 'client', lambda _: SearchProvider())
    route = application.performer_detail if kind == 'performer' else application.studio_detail
    def slow_read(*_): time.sleep(.15)
    event.listen(engine, 'before_cursor_execute', slow_read)
    try:
        with factory() as db:
            started = time.monotonic()
            task = asyncio.create_task(route('slow-detail', db=db, settings=Settings()))
            await asyncio.sleep(.02)
            elapsed = time.monotonic() - started
            await task
        assert elapsed < .1, f'Detail lookup blocked other requests for {elapsed:.3f}s'
    finally:
        event.remove(engine, 'before_cursor_execute', slow_read)
