from contextlib import asynccontextmanager
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.db import Base
from scarletx.models import Performer, Scene, Studio
from scarletx.schemas import RemotePerson, RemoteScene, RemoteStudio, SearchResponse
from scarletx.wanted import calendar_items


def make_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def remote_scene(scene_id="scene-1", *, future=False):
    performer = RemotePerson(id="person-1", search_id=10, name="Performer One")
    studio = RemoteStudio(id="studio-1", search_id=77, name="Studio One")
    return RemoteScene(
        id=scene_id,
        title="Future Scene" if future else "New Scene",
        release_date=date.today() + timedelta(days=7) if future else date.today(),
        studio=studio,
        performers=[performer],
    )


class FakeMetadata:
    def __init__(self, *, performer_error=False, future=False):
        self.performer_error = performer_error
        self.scene = remote_scene(future=future)
        self.performer_calls = 0
        self.studio_calls = 0

    async def get_performer_scenes(self, identifier, page=1, per_page=48):
        self.performer_calls += 1
        if self.performer_error:
            raise RuntimeError("performer failed")
        return SearchResponse(items=[self.scene] if page == 1 else [], total=1, page=page, per_page=per_page)

    async def get_studio(self, identifier):
        assert identifier == "studio-1"
        return RemoteStudio(id="studio-1", search_id=77, name="Studio One")

    async def search_scenes(self, query=None, page=1, per_page=48, performer_id=None, site_id=None):
        self.studio_calls += 1
        assert site_id == "77"
        return SearchResponse(items=[self.scene] if page == 1 else [], total=1, page=page, per_page=per_page)


@pytest.mark.asyncio
async def test_monitored_performer_and_studio_discovery_is_persistent_and_deduplicated(monkeypatch):
    from scarletx import monitored_entities

    factory = make_factory()
    with factory() as db:
        db.add(Performer(tpdb_id="person-1", name="Performer One", monitored=True, is_library=True))
        db.add(Studio(tpdb_id="studio-1", name="Studio One", monitored=True, is_library=True))
        db.commit()

    fake = FakeMetadata()

    @asynccontextmanager
    async def fake_client(_settings):
        yield fake

    monkeypatch.setattr(monitored_entities, "client", fake_client)
    result = await monitored_entities.monitored_entity_discovery_cycle(factory, object())

    assert result["entities_checked"] == 2
    assert result["unique_scenes"] == 1
    assert result["errors"] == []
    with factory() as db:
        rows = db.scalars(select(Scene)).all()
        assert len(rows) == 1
        assert rows[0].tpdb_id == "scene-1"
        assert rows[0].monitored is True
        assert db.scalar(select(Performer).where(Performer.tpdb_id == "person-1")).monitored is True
        assert db.scalar(select(Studio).where(Studio.tpdb_id == "studio-1")).monitored is True


@pytest.mark.asyncio
async def test_entity_failure_does_not_block_other_monitored_entities(monkeypatch):
    from scarletx import monitored_entities

    factory = make_factory()
    with factory() as db:
        db.add(Performer(tpdb_id="person-1", name="Performer One", monitored=True, is_library=True))
        db.add(Studio(tpdb_id="studio-1", name="Studio One", monitored=True, is_library=True))
        db.commit()

    fake = FakeMetadata(performer_error=True)

    @asynccontextmanager
    async def fake_client(_settings):
        yield fake

    monkeypatch.setattr(monitored_entities, "client", fake_client)
    result = await monitored_entities.monitored_entity_discovery_cycle(factory, object())

    assert result["entities_checked"] == 2
    assert len(result["errors"]) == 1
    with factory() as db:
        assert db.scalar(select(Scene).where(Scene.tpdb_id == "scene-1")) is not None


@pytest.mark.asyncio
async def test_future_scene_from_monitored_entity_appears_in_calendar(monkeypatch):
    from scarletx import monitored_entities

    factory = make_factory()
    with factory() as db:
        db.add(Performer(tpdb_id="person-1", name="Performer One", monitored=True, is_library=True))
        db.commit()

    fake = FakeMetadata(future=True)

    @asynccontextmanager
    async def fake_client(_settings):
        yield fake

    monkeypatch.setattr(monitored_entities, "client", fake_client)
    await monitored_entities.monitored_entity_discovery_cycle(factory, object())

    with factory() as db:
        items = calendar_items(db, date.today(), date.today() + timedelta(days=30))
    assert [item["title"] for item in items] == ["Future Scene"]
