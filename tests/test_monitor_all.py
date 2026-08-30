import asyncio
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx import main
from scarletx.db import Base
from scarletx.models import BackgroundJob
from scarletx.schemas import SearchResponse


class HangingMetadata:
    async def get_performer_scenes(self, _identifier, page, per_page):
        if page == 2:
            await asyncio.sleep(60)
        return SearchResponse(items=[], total=200, page=page, per_page=per_page)


@asynccontextmanager
async def hanging_client(_settings):
    yield HangingMetadata()


@pytest.mark.asyncio
async def test_monitor_all_stops_when_a_metadata_page_hangs(monkeypatch):
    monkeypatch.setattr(main, "client", hanging_client)
    monkeypatch.setattr(main, "ENTITY_PAGE_TIMEOUT_SECONDS", 0.01)

    scenes, warning = await main._all_adult_entity_scenes("performer", "person-1", object())

    assert scenes == []
    assert "page 2 timed out" in warning


def test_monitor_all_reuses_an_active_job(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    class Tasks:
        def __init__(self):
            self.calls = []

        def add_task(self, *args):
            self.calls.append(args)

    tasks = Tasks()
    with session_factory() as db:
        first = main._queue_adult_entity_monitor_search(db, tasks, "performer", "person-1", object())
        second = main._queue_adult_entity_monitor_search(db, tasks, "performer", "person-1", object())
        jobs = db.query(BackgroundJob).all()

    assert first == second
    assert len(jobs) == 1
    assert len(tasks.calls) == 1
