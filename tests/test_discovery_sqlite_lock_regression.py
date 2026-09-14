from contextlib import asynccontextmanager
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
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


class StableDeepPerformerMetadata:
    def __init__(self):
        self.performer = RemotePerson(id="performer-1", search_id=10, name="Performer One")
        self.studio = RemoteStudio(id="studio-1", search_id=77, name="Studio One")
        self.scenes = [
            RemoteScene(
                id="scene-1",
                title="Stable Scene One",
                release_date=date.today() + timedelta(days=5),
                studio=self.studio,
                performers=[self.performer],
            ),
            RemoteScene(
                id="scene-2",
                title="Stable Scene Two",
                release_date=date.today() + timedelta(days=15),
                studio=self.studio,
                performers=[self.performer],
            ),
        ]

    async def get_performer_scenes(self, identifier, page=1, per_page=48):
        assert identifier == "performer-1"
        return SearchResponse(
            items=self.scenes if page == 1 else [],
            total=len(self.scenes),
            page=page,
            per_page=per_page,
        )


@pytest.mark.asyncio
async def test_daily_deep_refresh_does_not_rewrite_unchanged_existing_scenes(monkeypatch):
    from scarletx import monitored_entities

    factory = make_factory()
    with factory() as db:
        performer = Performer(
            tpdb_id="performer-1",
            name="Performer One",
            monitored=True,
            is_library=True,
        )
        db.add(performer)
        db.commit()
        performer_id = performer.id

    fake = StableDeepPerformerMetadata()

    @asynccontextmanager
    async def fake_client(_settings):
        yield fake

    monkeypatch.setattr(monitored_entities, "client", fake_client)

    first = await monitored_entities.monitored_entity_discovery_cycle(factory, object())
    assert first["created"] == 2

    with factory() as db:
        marker = db.get(AppSetting, f"monitored_scan:performer_deep:{performer_id}")
        assert marker is not None
        marker.value = (date.today() - timedelta(days=1)).isoformat()
        db.commit()

    original_upsert = monitored_entities.upsert_scene
    writes = []

    def counted_upsert(*args, **kwargs):
        writes.append(args[1].id)
        return original_upsert(*args, **kwargs)

    monkeypatch.setattr(monitored_entities, "upsert_scene", counted_upsert)

    second = await monitored_entities.monitored_entity_discovery_cycle(factory, object())

    assert second["errors"] == []
    assert second["created"] == 0
    assert second["refreshed"] == 0
    assert writes == []

    with factory() as db:
        marker = db.get(AppSetting, f"monitored_scan:performer_deep:{performer_id}")
        assert marker is not None
        assert marker.value == date.today().isoformat()
