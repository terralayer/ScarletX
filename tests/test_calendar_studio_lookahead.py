# Calendar includes any scene monitored directly or through a monitored studio/performer.
import asyncio
import time
from contextlib import asynccontextmanager
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.db import Base
from scarletx.models import AppSetting, Performer, Scene, Studio, scene_performer
from scarletx.routes.application import calendar as calendar_route
from scarletx.schemas import RemotePerson, RemoteScene, RemoteStudio, SearchResponse
from scarletx.wanted import calendar_items


def make_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_calendar_defaults_to_next_30_days():
    factory = make_factory()
    today = date.today()
    with factory() as db:
        studio = Studio(tpdb_id="studio-1", name="Studio One", monitored=True, is_library=True)
        db.add(studio)
        db.flush()
        db.add_all([
            Scene(
                tpdb_id="scene-30",
                title="Day Thirty",
                content_type="scene",
                release_date=today + timedelta(days=30),
                studio_id=studio.id,
            ),
            Scene(
                tpdb_id="scene-31",
                title="Day Thirty One",
                content_type="scene",
                release_date=today + timedelta(days=31),
                studio_id=studio.id,
            ),
        ])
        db.commit()
        items = calendar_route(start=None, end=None, limit=500, db=db)

    assert [item["title"] for item in items] == ["Day Thirty"]


def test_calendar_membership_includes_anything_monitored():
    factory = make_factory()
    future = date.today() + timedelta(days=7)
    with factory() as db:
        monitored_studio = Studio(tpdb_id="studio-mon", name="Monitored Studio", monitored=True, is_library=True)
        other_studio = Studio(tpdb_id="studio-other", name="Other Studio", monitored=False, is_library=True)
        performer = Performer(tpdb_id="performer-1", name="Performer One", monitored=True, is_library=True)
        db.add_all([monitored_studio, other_studio, performer])
        db.flush()

        studio_scene = Scene(
            tpdb_id="studio-scene",
            title="Studio Scene",
            content_type="scene",
            monitored=False,
            release_date=future,
            studio_id=monitored_studio.id,
        )
        performer_scene = Scene(
            tpdb_id="performer-scene",
            title="Performer Scene",
            content_type="scene",
            monitored=False,
            release_date=future,
            studio_id=other_studio.id,
        )
        direct_scene = Scene(
            tpdb_id="direct-scene",
            title="Direct Scene",
            content_type="scene",
            monitored=True,
            release_date=future,
            studio_id=other_studio.id,
        )
        unmonitored_scene = Scene(
            tpdb_id="unmonitored-scene",
            title="Unmonitored Scene",
            content_type="scene",
            monitored=False,
            release_date=future,
            studio_id=other_studio.id,
        )
        db.add_all([studio_scene, performer_scene, direct_scene, unmonitored_scene])
        db.flush()
        db.execute(scene_performer.insert().values(scene_id=performer_scene.id, performer_id=performer.id))
        db.commit()

        items = calendar_items(db, date.today(), date.today() + timedelta(days=30), limit=500)

    assert [item["title"] for item in items] == ["Direct Scene", "Performer Scene", "Studio Scene"]


class DeepStudioMetadata:
    def __init__(self):
        self.calls = []
        self.studio = RemoteStudio(id="studio-1", search_id=77, name="Studio One")
        self.first = RemoteScene(
            id="scene-head",
            title="Head Scene",
            release_date=date.today() + timedelta(days=5),
            studio=self.studio,
            performers=[],
        )
        self.deep = RemoteScene(
            id="scene-deep",
            title="Deep Future Scene",
            release_date=date.today() + timedelta(days=20),
            studio=self.studio,
            performers=[],
        )

    async def get_studio(self, identifier):
        assert identifier == "studio-1"
        return self.studio

    async def search_scenes(self, query=None, page=1, per_page=48, performer_id=None, site_id=None):
        assert site_id == "77"
        self.calls.append(page)
        if page == 1:
            return SearchResponse(items=[self.first], total=49, page=1, per_page=per_page)
        if page == 2:
            return SearchResponse(items=[self.deep], total=49, page=2, per_page=per_page)
        return SearchResponse(items=[], total=49, page=page, per_page=per_page)


@pytest.mark.asyncio
async def test_monitored_studio_gets_one_deep_refresh_per_day(monkeypatch):
    from scarletx import monitored_entities

    factory = make_factory()
    with factory() as db:
        studio = Studio(tpdb_id="studio-1", name="Studio One", monitored=True, is_library=True)
        db.add(studio)
        db.commit()
        studio_id = studio.id

    fake = DeepStudioMetadata()

    @asynccontextmanager
    async def fake_client(_settings):
        yield fake

    monkeypatch.setattr(monitored_entities, "client", fake_client)

    first = await monitored_entities.monitored_entity_discovery_cycle(factory, object())
    assert first["created"] == 2
    assert fake.calls == [1, 2]

    second = await monitored_entities.monitored_entity_discovery_cycle(factory, object())
    assert second["unchanged_entities"] == 1
    assert fake.calls == [1, 2, 1]

    with factory() as db:
        key = f"monitored_scan:studio_deep:{studio_id}"
        marker = db.get(AppSetting, key)
        assert marker is not None
        marker.value = (date.today() - timedelta(days=1)).isoformat()
        db.commit()

    third = await monitored_entities.monitored_entity_discovery_cycle(factory, object())
    assert third["unchanged_entities"] == 0
    assert fake.calls == [1, 2, 1, 1, 2]

    with factory() as db:
        items = calendar_items(db, date.today(), date.today() + timedelta(days=30), limit=500)
    assert [item["title"] for item in items] == ["Head Scene", "Deep Future Scene"]


class DeepPerformerMetadata:
    def __init__(self):
        self.calls = []
        self.performer = RemotePerson(id="performer-1", search_id=10, name="Performer One")
        self.studio = RemoteStudio(id="performer-studio", search_id=88, name="Performer Studio")
        self.first = RemoteScene(
            id="performer-head",
            title="Performer Head Scene",
            release_date=date.today() + timedelta(days=4),
            studio=self.studio,
            performers=[self.performer],
        )
        self.deep = RemoteScene(
            id="performer-deep",
            title="Performer Deep Future Scene",
            release_date=date.today() + timedelta(days=18),
            studio=self.studio,
            performers=[self.performer],
        )

    async def get_performer_scenes(self, identifier, page=1, per_page=48):
        assert identifier == "performer-1"
        self.calls.append(page)
        if page == 1:
            return SearchResponse(items=[self.first], total=49, page=1, per_page=per_page)
        if page == 2:
            return SearchResponse(items=[self.deep], total=49, page=2, per_page=per_page)
        return SearchResponse(items=[], total=49, page=page, per_page=per_page)


@pytest.mark.asyncio
async def test_monitored_performer_gets_one_deep_refresh_per_day(monkeypatch):
    from scarletx import monitored_entities

    factory = make_factory()
    with factory() as db:
        performer = Performer(tpdb_id="performer-1", name="Performer One", monitored=True, is_library=True)
        db.add(performer)
        db.commit()
        performer_id = performer.id

    fake = DeepPerformerMetadata()

    @asynccontextmanager
    async def fake_client(_settings):
        yield fake

    monkeypatch.setattr(monitored_entities, "client", fake_client)

    first = await monitored_entities.monitored_entity_discovery_cycle(factory, object())
    assert first["created"] == 2
    assert fake.calls == [1, 2]

    with factory() as db:
        key = f"monitored_scan:performer_deep:{performer_id}"
        marker = db.get(AppSetting, key)
        assert marker is not None

    second = await monitored_entities.monitored_entity_discovery_cycle(factory, object())
    assert second["unchanged_entities"] == 1
    assert fake.calls == [1, 2, 1]

    with factory() as db:
        marker = db.get(AppSetting, f"monitored_scan:performer_deep:{performer_id}")
        marker.value = (date.today() - timedelta(days=1)).isoformat()
        db.commit()

    third = await monitored_entities.monitored_entity_discovery_cycle(factory, object())
    assert third["unchanged_entities"] == 0
    assert fake.calls == [1, 2, 1, 1, 2]

    with factory() as db:
        items = calendar_items(db, date.today(), date.today() + timedelta(days=30), limit=500)
    assert [item["title"] for item in items] == [
        "Performer Head Scene",
        "Performer Deep Future Scene",
    ]


class PersistenceLoadMetadata:
    def __init__(self):
        self.studio = RemoteStudio(id="load-studio", search_id=99, name="Load Studio")
        self.scenes = [
            RemoteScene(
                id=f"load-{i}",
                title=f"Load Scene {i}",
                release_date=date.today() + timedelta(days=i + 1),
                studio=self.studio,
                performers=[],
            )
            for i in range(5)
        ]

    async def get_studio(self, identifier):
        return self.studio

    async def search_scenes(self, query=None, page=1, per_page=48, performer_id=None, site_id=None):
        return SearchResponse(items=self.scenes if page == 1 else [], total=5, page=page, per_page=per_page)


@pytest.mark.asyncio
async def test_large_discovery_persistence_does_not_block_event_loop(monkeypatch):
    from scarletx import monitored_entities

    factory = make_factory()
    with factory() as db:
        db.add(Studio(tpdb_id="load-studio", name="Load Studio", monitored=True, is_library=True))
        db.commit()

    fake = PersistenceLoadMetadata()

    @asynccontextmanager
    async def fake_client(_settings):
        yield fake

    ticks = [0]
    observations = []
    stop = asyncio.Event()

    async def ticker():
        while not stop.is_set():
            ticks[0] += 1
            await asyncio.sleep(0.005)

    def slow_upsert(_db, _remote, monitored=True, content_type="scene", commit=False):
        observations.append(ticks[0])
        time.sleep(0.03)
        return SimpleNamespace(monitored=True, id=len(observations))

    monkeypatch.setattr(monitored_entities, "client", fake_client)
    monkeypatch.setattr(monitored_entities, "upsert_scene", slow_upsert)

    ticker_task = asyncio.create_task(ticker())
    await asyncio.sleep(0.01)
    try:
        await monitored_entities.monitored_entity_discovery_cycle(factory, object())
    finally:
        stop.set()
        await ticker_task

    assert len(observations) == 5
    assert max(observations) > min(observations)
