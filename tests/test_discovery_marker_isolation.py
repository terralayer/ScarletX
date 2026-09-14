from contextlib import asynccontextmanager
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.db import Base
from scarletx.models import AppSetting, Performer
from scarletx.schemas import RemotePerson, RemoteScene, RemoteStudio, SearchResponse


def make_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


class TwoPerformerMetadata:
    def __init__(self):
        self.good_performer = RemotePerson(id="performer-good", search_id=1, name="Good Performer")
        self.bad_performer = RemotePerson(id="performer-bad", search_id=2, name="Bad Performer")
        self.studio = RemoteStudio(id="studio-1", search_id=99, name="Studio One")
        future = date.today() + timedelta(days=7)
        self.scenes = {
            "performer-good": RemoteScene(
                id="scene-good",
                title="Good Scene",
                release_date=future,
                studio=self.studio,
                performers=[self.good_performer],
            ),
            "performer-bad": RemoteScene(
                id="scene-bad",
                title="Bad Scene",
                release_date=future,
                studio=self.studio,
                performers=[self.bad_performer],
            ),
        }

    async def get_performer_scenes(self, identifier, page=1, per_page=48):
        scene = self.scenes[identifier]
        return SearchResponse(items=[scene], total=1, page=page, per_page=per_page)


@pytest.mark.asyncio
async def test_transient_sqlite_lock_retries_scene_write_and_advances_marker(monkeypatch):
    from scarletx import monitored_entities

    factory = make_factory()
    with factory() as db:
        performer = Performer(
            tpdb_id="performer-good",
            name="Good Performer",
            monitored=True,
            is_library=True,
        )
        db.add(performer)
        db.commit()
        performer_id = performer.id

    fake = TwoPerformerMetadata()

    @asynccontextmanager
    async def fake_client(_settings):
        yield fake

    attempts = 0

    def flaky_upsert(_db, remote, monitored=True, content_type="scene", commit=False):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OperationalError("DELETE FROM scene_performer", {}, Exception("database is locked"))
        return SimpleNamespace(monitored=True, id=101)

    with factory() as db:
        bad = db.query(Performer).filter(Performer.tpdb_id == "performer-bad").one_or_none()
        if bad is not None:
            db.delete(bad)
            db.commit()

    monkeypatch.setattr(monitored_entities, "client", fake_client)
    monkeypatch.setattr(monitored_entities, "upsert_scene", flaky_upsert)
    monkeypatch.setattr(monitored_entities.time, "sleep", lambda _seconds: None, raising=False)

    result = await monitored_entities.monitored_entity_discovery_cycle(factory, object())

    assert attempts == 3
    assert result["errors"] == []

    with factory() as db:
        marker = db.get(AppSetting, f"monitored_scan:performer_deep:{performer_id}")

    assert marker is not None
    assert marker.value == date.today().isoformat()


@pytest.mark.asyncio
async def test_scene_failure_only_keeps_own_entity_deep_scan_due(monkeypatch):
    from scarletx import monitored_entities

    factory = make_factory()
    with factory() as db:
        good = Performer(tpdb_id="performer-good", name="Good Performer", monitored=True, is_library=True)
        bad = Performer(tpdb_id="performer-bad", name="Bad Performer", monitored=True, is_library=True)
        db.add_all([good, bad])
        db.commit()
        good_id = good.id
        bad_id = bad.id

    fake = TwoPerformerMetadata()

    @asynccontextmanager
    async def fake_client(_settings):
        yield fake

    next_id = iter((101, 102))

    def fake_upsert(_db, remote, monitored=True, content_type="scene", commit=False):
        if remote.id == "scene-bad":
            raise RuntimeError("forced scene persistence failure")
        return SimpleNamespace(monitored=True, id=next(next_id))

    monkeypatch.setattr(monitored_entities, "client", fake_client)
    monkeypatch.setattr(monitored_entities, "upsert_scene", fake_upsert)

    result = await monitored_entities.monitored_entity_discovery_cycle(factory, object())

    assert len(result["errors"]) == 1
    assert result["errors"][0]["id"] == "scene-bad"

    with factory() as db:
        good_marker = db.get(AppSetting, f"monitored_scan:performer_deep:{good_id}")
        bad_marker = db.get(AppSetting, f"monitored_scan:performer_deep:{bad_id}")

    assert good_marker is not None
    assert good_marker.value == date.today().isoformat()
    assert bad_marker is None
