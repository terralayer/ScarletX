import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx import entity_hydration
from scarletx.db import Base
from scarletx.models import BackgroundJob, Performer, Scene, Studio
from scarletx.schemas import RemotePerson, RemoteScene, RemoteStudio, SearchResponse


@pytest.mark.parametrize('kind', ['performer', 'studio'])
@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('path', ['detail', 'summary'])
def test_any_monitored_credit_monitors_discovered_scene(factory, kind, existing, path):
    from scarletx.services import upsert_scene
    with factory() as db:
        db.add(Performer(tpdb_id='person', name='Person', monitored=kind == 'performer'))
        db.add(Studio(tpdb_id='studio', name='Studio', monitored=kind == 'studio'))
        if existing:
            db.add(Scene(tpdb_id='scene', title='Scene', monitored=False))
        db.commit()
    remote = RemoteScene(id='scene', title='Scene', studio=RemoteStudio(id='studio', name='Studio'), performers=[RemotePerson(id='person', name='Person')])
    if path == 'summary':
        entity_hydration.cache_entity_scene_summaries([remote], False)
    else:
        with factory() as db:
            upsert_scene(db, remote, monitored=False)
    with factory() as db:
        assert db.scalar(select(Scene)).monitored is True


def test_existing_scenes_inherit_monitoring_without_unmonitoring_others(factory):
    from scarletx.services import inherit_scene_monitoring
    with factory() as db:
        person = Performer(tpdb_id='person', name='Person', monitored=True)
        studio = Studio(tpdb_id='studio', name='Studio', monitored=True)
        db.add_all([
            Scene(tpdb_id='person-scene', title='Person scene', monitored=False, performers=[person]),
            Scene(tpdb_id='studio-scene', title='Studio scene', monitored=False, studio=studio),
            Scene(tpdb_id='manual-scene', title='Manual scene', monitored=True),
            Scene(tpdb_id='other-scene', title='Other scene', monitored=False),
        ])
        db.commit()
        inherit_scene_monitoring(db)
        db.commit()
        assert {s.tpdb_id for s in db.scalars(select(Scene)).all() if s.monitored} == {'person-scene', 'studio-scene', 'manual-scene'}


def test_yourvids_is_not_a_studio_and_existing_library_entry_is_hidden(factory):
    from scarletx.studio_policy import is_allowed_tpdb_site_raw, is_allowed_remote_scene
    from scarletx.list_queries import studio_summary_page
    assert not is_allowed_tpdb_site_raw({'uuid': 'blocked', 'name': 'Yourvids: Creator', 'url': 'https://yourvidscreator.com'})
    assert not is_allowed_remote_scene(RemoteScene(id='blocked-scene', title='Scene', source_url='https://yourvids.com/vids/example', studio=RemoteStudio(id='site', name='Creator')))
    with factory() as db:
        db.add_all([Studio(tpdb_id='blocked', name='Yourvids: Creator', is_library=True), Studio(tpdb_id='allowed', name='Production Studio', is_library=True)])
        db.commit()
        result = studio_summary_page(db, limit=20)
        assert [row['tpdb_id'] for row in result['items']] == ['allowed']
        assert result['total'] == 1
        assert db.scalar(select(Studio).where(Studio.tpdb_id == 'blocked')) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['performer', 'studio'])
async def test_monitor_button_immediately_monitors_saved_scenes(factory, monkeypatch, kind):
    from fastapi import BackgroundTasks
    from scarletx.routes import application
    from scarletx.config import Settings
    from scarletx.schemas import ImportRequest
    monkeypatch.setattr(application, '_queue_adult_entity_monitor_search', lambda *args: 42)
    model = Performer if kind == 'performer' else Studio
    monitor = application.monitor_performer if kind == 'performer' else application.monitor_studio
    with factory() as db:
        owner = model(tpdb_id='owner', name='Owner', is_library=True, monitored=False)
        scene = Scene(tpdb_id='scene', title='Scene', monitored=False)
        if kind == 'performer':
            scene.performers = [owner]
        else:
            scene.studio = owner
        db.add(scene)
        db.commit()
        result = await monitor(owner.id, ImportRequest(monitored=True), BackgroundTasks(), db, Settings())
        assert result['monitored'] is True
        db.refresh(scene)
        assert scene.monitored is True
        await monitor(owner.id, ImportRequest(monitored=False), BackgroundTasks(), db, Settings())
        db.refresh(scene)
        assert scene.monitored is True


def test_legacy_blocked_sources_are_excluded_from_profile_and_monitor_inheritance(factory):
    from scarletx.services import inherit_scene_monitoring
    from scarletx.routes.application import performer_cached_scenes
    with factory() as db:
        owner = Performer(tpdb_id='owner', name='Owner', is_library=True, monitored=True)
        allowed = Studio(tpdb_id='allowed', name='Production Studio')
        blocked = Studio(tpdb_id='blocked', name='Yourvids: Creator')
        db.add_all([
            Scene(tpdb_id='allowed-scene', title='Allowed', studio=allowed, monitored=False, performers=[owner]),
            Scene(tpdb_id='blocked-studio-scene', title='Blocked studio', studio=blocked, monitored=False, performers=[owner]),
            Scene(tpdb_id='blocked-url-scene', title='Blocked URL', studio=allowed, source_url='https://yourvids.com/vids/example', monitored=False, performers=[owner]),
        ])
        db.commit()
        inherit_scene_monitoring(db)
        db.commit()
        assert {s.tpdb_id for s in db.scalars(select(Scene)).all() if s.monitored} == {'allowed-scene'}
        result = performer_cached_scenes(owner.id, page=1, per_page=1, db=db)
        assert result['total'] == 1
        assert [s['id'] for s in result['items']] == ['allowed-scene']
        assert len(db.scalars(select(Scene)).all()) == 3


@pytest.fixture
def factory(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(entity_hydration, 'SessionLocal', factory)
    yield factory
    engine.dispose()


class CappedPages:
    async def get_performer_scenes(self, identifier, page, per_page):
        # The provider caps the requested 100 rows at two. Page 2 is filtered out.
        items = [] if page == 2 else [RemoteScene(id=f'scene-{page}', title=f'Scene {page}', studio=RemoteStudio(id='studio', name='Studio'))]
        return SearchResponse(items=items, total=6, page=page, per_page=2)


def test_catalog_status_reports_never_checked_with_null_timestamps(factory):
    from scarletx.scene_catalog import scene_catalog_status

    with factory() as db:
        status = scene_catalog_status(db, 'performer', 'person')

    assert status == {
        'job_id': None,
        'status': 'not_started',
        'scenes_cached': 0,
        'pages_fetched': 0,
        'provider_total': None,
        'error': None,
        'queued_at': None,
        'finished_at': None,
        'last_success_at': None,
    }


@pytest.mark.parametrize('job_status', ['queued', 'running'])
def test_catalog_status_reports_active_progress_and_queued_time(factory, job_status):
    from scarletx.scene_catalog import scene_catalog_status

    queued_at = datetime(2026, 9, 19, 17, 30, tzinfo=UTC)
    with factory() as db:
        db.add(BackgroundJob(
            kind='performer_scene_catalog',
            status=job_status,
            created_at=queued_at,
            payload=json.dumps({
                'identifier': 'person',
                'pages_fetched': 2,
                'scenes_cached': 7,
                'provider_total': 12,
            }),
        ))
        db.commit()
        status = scene_catalog_status(db, 'performer', 'person')

    assert status['status'] == job_status
    assert status['pages_fetched'] == 2
    assert status['scenes_cached'] == 7
    assert status['provider_total'] == 12
    assert status['queued_at'] == '2026-09-19T17:30:00+00:00'
    assert status['finished_at'] is None
    assert status['last_success_at'] is None


def test_catalog_status_reports_completed_job_as_last_success(factory):
    from scarletx.scene_catalog import scene_catalog_status

    with factory() as db:
        db.add(BackgroundJob(
            kind='studio_scene_catalog',
            status='completed',
            created_at=datetime(2026, 9, 19, 16, 0, tzinfo=UTC),
            finished_at=datetime(2026, 9, 19, 16, 5, tzinfo=UTC),
            payload=json.dumps({
                'identifier': 'studio',
                'pages_fetched': 3,
                'scenes_cached': 9,
            }),
        ))
        db.commit()
        status = scene_catalog_status(db, 'studio', 'studio')

    assert status['status'] == 'completed'
    assert status['queued_at'] == '2026-09-19T16:00:00+00:00'
    assert status['finished_at'] == '2026-09-19T16:05:00+00:00'
    assert status['last_success_at'] == '2026-09-19T16:05:00+00:00'


def test_catalog_status_keeps_last_success_after_later_failure(factory):
    from scarletx.scene_catalog import scene_catalog_status

    with factory() as db:
        db.add_all([
            BackgroundJob(
                kind='performer_scene_catalog',
                status='completed',
                created_at=datetime(2026, 9, 18, 20, 0, tzinfo=UTC),
                finished_at=datetime(2026, 9, 18, 20, 15, tzinfo=UTC),
                payload=json.dumps({'identifier': 'person', 'pages_fetched': 5, 'scenes_cached': 20}),
            ),
            BackgroundJob(
                kind='performer_scene_catalog',
                status='failed',
                error='Provider unavailable',
                created_at=datetime(2026, 9, 19, 18, 0, tzinfo=UTC),
                finished_at=datetime(2026, 9, 19, 18, 2, tzinfo=UTC),
                payload=json.dumps({'identifier': 'person', 'pages_fetched': 2, 'scenes_cached': 6}),
            ),
            BackgroundJob(
                kind='performer_scene_catalog',
                status='completed',
                created_at=datetime(2026, 9, 19, 19, 0, tzinfo=UTC),
                finished_at=datetime(2026, 9, 19, 19, 1, tzinfo=UTC),
                payload=json.dumps({'identifier': 'someone-else'}),
            ),
        ])
        db.commit()
        status = scene_catalog_status(db, 'performer', 'person')

    assert status['status'] == 'failed'
    assert status['error'] == 'Provider unavailable'
    assert status['pages_fetched'] == 2
    assert status['scenes_cached'] == 6
    assert status['finished_at'] == '2026-09-19T18:02:00+00:00'
    assert status['last_success_at'] == '2026-09-18T20:15:00+00:00'


@pytest.mark.asyncio
async def test_full_scan_uses_returned_page_size_and_crosses_filtered_empty_pages():
    scenes = await entity_hydration._entity_scene_summaries(CappedPages(), 'performer', 'person')
    assert [x.id for x in scenes] == ['scene-1', 'scene-3']


def test_summary_cache_links_performers_without_erasing_richer_local_metadata(factory):
    with factory() as db:
        performer = Performer(tpdb_id='person', name='Person', bio='Full biography', is_library=True)
        db.add(Scene(tpdb_id='scene', title='Scene', description='Full description', image_url='https://example.com/image.jpg', performers=[performer]))
        db.commit()
    summary = RemoteScene(id='scene', title='Scene', studio=RemoteStudio(id='studio', name='Studio'), performers=[RemotePerson(id='person', name='Person'), RemotePerson(id='other', name='Other')])
    entity_hydration.cache_entity_scene_summaries([summary], monitored=False)
    with factory() as db:
        scene = db.scalar(select(Scene).where(Scene.tpdb_id == 'scene'))
        assert {p.tpdb_id for p in scene.performers} == {'person', 'other'}
        assert scene.description == 'Full description'
        assert scene.image_url == 'https://example.com/image.jpg'
        assert db.scalar(select(Performer).where(Performer.tpdb_id == 'person')).bio == 'Full biography'


@pytest.mark.parametrize('failure', ['unique', 'locked'])
def test_summary_cache_retries_concurrent_write_conflicts(factory, failure):
    from sqlalchemy import event
    from sqlalchemy.exc import IntegrityError, OperationalError
    engine = factory.kw['bind']
    injected = []
    def concurrent_writer(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('INSERT INTO scenes') and not injected:
            injected.append(True)
            error = IntegrityError if failure == 'unique' else OperationalError
            reason = 'UNIQUE constraint failed: scenes.tpdb_id' if failure == 'unique' else 'database is locked'
            raise error(statement, parameters, Exception(reason))
    event.listen(engine, 'before_cursor_execute', concurrent_writer)
    try:
        ids = entity_hydration.cache_entity_scene_summaries([RemoteScene(id='scene', title='Scene', studio=RemoteStudio(id='studio', name='Studio'))], False)
        assert injected
        assert len(ids) == 1
        with factory() as db:
            assert len(db.scalars(select(Scene)).all()) == 1
            assert len(db.scalars(select(Studio)).all()) == 1
    finally:
        event.remove(engine, 'before_cursor_execute', concurrent_writer)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['performer', 'studio'])
@pytest.mark.parametrize('monitored', [False, True])
async def test_profile_catalog_is_saved_once_and_can_be_explicitly_refreshed(factory, monkeypatch, kind, monitored):
    from fastapi import BackgroundTasks
    from scarletx import scene_catalog
    from scarletx.config import Settings
    monkeypatch.setattr(scene_catalog, 'SessionLocal', factory)
    class Provider(CappedPages):
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get_studio(self, identifier): return RemoteStudio(id='studio', name='Studio', search_id=42)
        async def search_scenes(self, **kwargs):
            assert kwargs['site_id'] == '42'
            return await self.get_performer_scenes('person', kwargs['page'], kwargs['per_page'])
    monkeypatch.setattr(scene_catalog, 'metadata_client', lambda settings, **kwargs: Provider())
    identifier = 'person' if kind == 'performer' else 'studio'
    model = Performer if kind == 'performer' else Studio
    with factory() as db:
        db.add(model(tpdb_id=identifier, name='Owner', is_library=True, monitored=monitored))
        db.commit()
        tasks = BackgroundTasks()
        started = scene_catalog.ensure_scene_catalog(db, tasks, kind, identifier, Settings())
        again = scene_catalog.ensure_scene_catalog(db, tasks, kind, identifier, Settings())
        assert started['job_id'] == again['job_id']
        assert len(tasks.tasks) == 1
    await tasks()
    with factory() as db:
        status = scene_catalog.scene_catalog_status(db, kind, identifier)
        assert status['status'] == 'completed'
        assert status['scenes_cached'] == 2
        assert status['pages_fetched'] == 3
        scenes = db.scalars(select(Scene).order_by(Scene.tpdb_id)).all()
        assert [s.tpdb_id for s in scenes] == ['scene-1', 'scene-3']
        assert all(s.monitored is monitored for s in scenes)
        if kind == 'performer':
            assert all('person' in {p.tpdb_id for p in s.performers} for s in scenes)
        else:
            assert all(s.studio.tpdb_id == 'studio' for s in scenes)
        no_tasks = BackgroundTasks()
        scene_catalog.ensure_scene_catalog(db, no_tasks, kind, identifier, Settings())
        assert not no_tasks.tasks
        refreshed = scene_catalog.ensure_scene_catalog(db, no_tasks, kind, identifier, Settings(), force=True)
        assert refreshed['job_id'] != started['job_id']
        assert len(no_tasks.tasks) == 1


@pytest.mark.parametrize('kind', ['performer', 'studio'])
@pytest.mark.parametrize('owner_monitored', [False, True])
def test_profile_scene_pages_include_all_monitoring_states(factory, kind, owner_monitored):
    from scarletx.routes.application import performer_cached_scenes, studio_cached_scenes
    model = Performer if kind == 'performer' else Studio
    page = performer_cached_scenes if kind == 'performer' else studio_cached_scenes
    with factory() as db:
        owner = model(tpdb_id='owner', name='Owner', is_library=True, monitored=owner_monitored)
        for index, monitored in enumerate([False, True, False]):
            scene = Scene(tpdb_id=f'scene-{index}', title=f'Scene {index}', monitored=monitored)
            if kind == 'performer':
                scene.performers = [owner]
            else:
                scene.studio = owner
            db.add(scene)
        db.commit()
        pages = [page(owner.id, page=n, per_page=1, db=db) for n in (1, 2, 3)]
        assert all(result['total'] == 3 for result in pages)
        assert {row['id']: row['monitored'] for result in pages for row in result['items']} == {
            'scene-0': False, 'scene-1': True, 'scene-2': False,
        }
        assert owner.monitored is owner_monitored


@pytest.mark.asyncio
async def test_failed_scan_keeps_saved_pages_and_is_not_reported_complete(factory, monkeypatch):
    from fastapi import BackgroundTasks
    from scarletx import scene_catalog
    from scarletx.config import Settings
    from scarletx.metadata import MetadataProviderError
    monkeypatch.setattr(scene_catalog, 'SessionLocal', factory)
    monkeypatch.setattr(entity_hydration, 'ENTITY_FETCH_ATTEMPTS', 1)
    class Provider(CappedPages):
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get_performer_scenes(self, identifier, page, per_page):
            if page == 3:
                raise MetadataProviderError('Provider unavailable')
            return await super().get_performer_scenes(identifier, page, per_page)
    monkeypatch.setattr(scene_catalog, 'metadata_client', lambda settings, **kwargs: Provider())
    with factory() as db:
        db.add(Performer(tpdb_id='person', name='Person', is_library=True))
        db.commit()
        tasks = BackgroundTasks()
        scene_catalog.ensure_scene_catalog(db, tasks, 'performer', 'person', Settings())
    await tasks()
    with factory() as db:
        status = scene_catalog.scene_catalog_status(db, 'performer', 'person')
        assert status['status'] == 'failed'
        assert status['scenes_cached'] == 1
        assert 'Provider unavailable' in status['error']
        assert db.scalar(select(Scene).where(Scene.tpdb_id == 'scene-1')) is not None
        assert db.scalar(select(BackgroundJob)).finished_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize('cache_mode', ['disk', 'memory', 'stale'])
async def test_catalog_cannot_report_up_to_date_from_cached_pages_during_outage(factory, monkeypatch, tmp_path, cache_mode):
    import os
    import time
    import httpx
    from fastapi import BackgroundTasks
    from scarletx import metadata, scene_catalog, tpdb
    from scarletx.async_cache import AsyncLRUCache
    from scarletx.config import Settings
    monkeypatch.setattr(scene_catalog, 'SessionLocal', factory)
    monkeypatch.setattr(tpdb, 'TPDB_CACHE_ROOT', tmp_path)
    monkeypatch.setattr(tpdb, '_TPDB_MEMORY_CACHE', AsyncLRUCache())
    monkeypatch.setattr(entity_hydration, 'ENTITY_FETCH_ATTEMPTS', 1)
    path = tpdb._cache_key('/performers/person/scenes', {'page': 1, 'per_page': 100})
    old_page = {'data': [], 'meta': {'total': 0, 'per_page': 100, 'current_page': 1}}
    tpdb._write_cache(path, old_page)
    if cache_mode == 'stale':
        os.utime(path, (0, 0))
    if cache_mode == 'memory':
        await tpdb._TPDB_MEMORY_CACHE.put(path, old_page, time.time() + 300)
    requests = []
    def unavailable(request):
        requests.append(request)
        return httpx.Response(503, json={'error': 'unavailable'})
    real_client = tpdb.ThePornDBClient
    monkeypatch.setattr(metadata, 'ThePornDBClient', lambda key, url, **kwargs: real_client(key, url, transport=httpx.MockTransport(unavailable), max_retries=1, **kwargs))
    with factory() as db:
        db.add(Performer(tpdb_id='person', name='Person', is_library=True))
        db.commit()
        tasks = BackgroundTasks()
        scene_catalog.ensure_scene_catalog(db, tasks, 'performer', 'person', Settings(theporndb_api_key='test'))
    await tasks()
    with factory() as db:
        status = scene_catalog.scene_catalog_status(db, 'performer', 'person')
        assert status['status'] == 'failed'
        assert 'unavailable' in status['error']
        assert requests
