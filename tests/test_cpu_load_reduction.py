from contextlib import asynccontextmanager
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.config import Settings
from scarletx.db import Base
from scarletx.models import AppSetting, NativeUsenetJob, Performer, TrackedDownload
from scarletx.schemas import RemotePerson, RemoteScene, RemoteStudio, SearchResponse


def make_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_download_processing_backs_off_when_idle_and_stays_responsive_when_active():
    from scarletx.download_processing import process_completed_downloads

    factory = make_factory()
    settings = Settings(completed_download_import_enabled=True)

    idle = await process_completed_downloads(factory, settings)
    assert idle["poll_seconds"] == 120

    with factory() as db:
        db.add(NativeUsenetJob(id="job-1", title="Scene", nzb_url="https://example.invalid/a.nzb", status="queued"))
        db.add(TrackedDownload(nzo_id="job-1", release_title="Scene", status="queued"))
        db.commit()

    active = await process_completed_downloads(factory, settings)
    assert active["poll_seconds"] == 60


@pytest.mark.asyncio
async def test_native_downloader_uses_idle_backoff_when_queue_is_empty(monkeypatch):
    from scarletx.usenet import worker

    factory = make_factory()
    sleeps = []

    async def stop_after_first_sleep(seconds):
        sleeps.append(seconds)
        raise asyncio.CancelledError

    import asyncio

    monkeypatch.setattr(worker.asyncio, "sleep", stop_after_first_sleep)
    with pytest.raises(asyncio.CancelledError):
        await worker.native_worker_loop(factory, lambda: Settings())

    assert sleeps == [5.0]


class PagedMetadata:
    def __init__(self):
        performer = RemotePerson(id="person-1", search_id=10, name="Performer One")
        studio = RemoteStudio(id="studio-1", search_id=77, name="Studio One")
        self.first = RemoteScene(
            id="scene-1", title="Newest Scene", release_date=date.today(), studio=studio, performers=[performer]
        )
        self.second = RemoteScene(
            id="scene-2", title="Older Scene", release_date=date.today(), studio=studio, performers=[performer]
        )
        self.performer_calls = 0

    async def get_performer_scenes(self, identifier, page=1, per_page=48):
        assert identifier == "person-1"
        self.performer_calls += 1
        items = [self.first] if page == 1 else [self.second] if page == 2 else []
        return SearchResponse(items=items, total=49, page=page, per_page=per_page)


@pytest.mark.asyncio
async def test_unchanged_monitored_entity_scan_uses_durable_head_cursor_and_skips_deep_pages(monkeypatch):
    from scarletx import monitored_entities

    factory = make_factory()
    with factory() as db:
        performer = Performer(tpdb_id="person-1", name="Performer One", monitored=True, is_library=True)
        db.add(performer)
        db.commit()
        performer_id = performer.id

    fake = PagedMetadata()

    @asynccontextmanager
    async def fake_client(_settings):
        yield fake

    monkeypatch.setattr(monitored_entities, "client", fake_client)

    first = await monitored_entities.monitored_entity_discovery_cycle(factory, object())
    assert first["created"] == 2
    assert fake.performer_calls == 2

    second = await monitored_entities.monitored_entity_discovery_cycle(factory, object())
    assert second["created"] == 0
    assert second["refreshed"] == 0
    assert second["unchanged_entities"] == 1
    assert set(second["scene_ids"]) == set(first["scene_ids"])
    assert fake.performer_calls == 3

    with factory() as db:
        cursor = db.get(AppSetting, f"monitored_scan:performer:{performer_id}")
        assert cursor is not None
        assert "scene-1" in cursor.value
