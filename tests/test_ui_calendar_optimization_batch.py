from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.db import Base
from scarletx.models import Performer, Scene, Studio, scene_performer
from scarletx.routes.application import calendar as calendar_route
from scarletx.schemas import RemotePerson, RemoteScene, RemoteStudio, SearchResponse

ROOT = Path(__file__).resolve().parents[1]


def make_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_entity_requests_use_page_local_sequence_not_global_navigation_generation():
    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "const seq=beginPageRequest('performers')" in source
    assert "const seq=beginPageRequest('studios')" in source
    assert "const seq=beginPageRequest('scenes')" in source
    assert "if(!pageRequestCurrent('performers',seq))return" in source
    assert "if(!pageRequestCurrent('studios',seq))return" in source
    assert "if(!pageRequestCurrent('scenes',seq))return" in source


def test_top_left_x_mark_is_removed_but_brand_word_remains():
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert '<div class="brandmark">X</div>' not in index
    assert '<div class="brand">ScarletX</div>' in index


def test_scene_and_library_studio_art_is_large_enough_to_read():
    css = (ROOT / "frontend" / "ui_overrides.css").read_text(encoding="utf-8")
    compact = "".join(css.split())
    assert ".scene-studio-logo{width:72px;height:44px" in compact
    assert ".media-studio-logo{width:64px;height:40px" in compact


def test_calendar_includes_future_scene_via_monitored_performer_relationship():
    factory = make_factory()
    today = date.today()
    with factory() as db:
        performer = Performer(tpdb_id="performer-1", name="Performer", monitored=True)
        scene = Scene(
            tpdb_id="scene-1",
            title="Future Performer Scene",
            release_date=today + timedelta(days=7),
            content_type="scene",
            monitored=False,
        )
        db.add_all([performer, scene])
        db.flush()
        db.execute(scene_performer.insert().values(scene_id=scene.id, performer_id=performer.id))
        db.commit()

        rows = calendar_route(start=today, end=today + timedelta(days=30), limit=500, db=db)

    assert [row["title"] for row in rows] == ["Future Performer Scene"]


def test_calendar_includes_future_scene_via_monitored_studio_relationship():
    factory = make_factory()
    today = date.today()
    with factory() as db:
        studio = Studio(tpdb_id="studio-1", name="Studio", monitored=True)
        scene = Scene(
            tpdb_id="scene-1",
            title="Future Studio Scene",
            release_date=today + timedelta(days=7),
            content_type="scene",
            monitored=False,
            studio=studio,
        )
        db.add(scene)
        db.commit()

        rows = calendar_route(start=today, end=today + timedelta(days=30), limit=500, db=db)

    assert [row["title"] for row in rows] == ["Future Studio Scene"]


def test_calendar_route_defaults_to_thirty_day_studio_window():
    source = (ROOT / "scarletx" / "routes" / "application.py").read_text(encoding="utf-8")
    compact = "".join(source.split())
    assert "end=endor(today+timedelta(days=30))" in compact


class UnchangedMetadata:
    def __init__(self):
        self.performer = RemotePerson(id="performer-1", search_id=1, name="Performer")
        self.scene = RemoteScene(
            id="existing-future",
            title="Existing Future",
            release_date=date.today() + timedelta(days=8),
            performers=[self.performer],
        )

    async def get_performer_scenes(self, identifier, page=1, per_page=48):
        return SearchResponse(items=[self.scene], total=1, page=page, per_page=per_page)


@pytest.mark.asyncio
async def test_hourly_discovery_promotes_existing_related_scene_to_monitored(monkeypatch):
    from scarletx import monitored_entities

    factory = make_factory()
    with factory() as db:
        performer = Performer(tpdb_id="performer-1", name="Performer", monitored=True)
        scene = Scene(
            tpdb_id="existing-future",
            title="Existing Future",
            release_date=date.today() + timedelta(days=8),
            content_type="scene",
            monitored=False,
        )
        db.add_all([performer, scene])
        db.flush()
        db.execute(scene_performer.insert().values(scene_id=scene.id, performer_id=performer.id))
        db.commit()

    fake = UnchangedMetadata()

    @asynccontextmanager
    async def fake_client(_settings):
        yield fake

    monkeypatch.setattr(monitored_entities, "client", fake_client)
    result = await monitored_entities.monitored_entity_discovery_cycle(factory, object())
    assert result["scene_ids"]
    with factory() as db:
        scene = db.scalar(select(Scene).where(Scene.tpdb_id == "existing-future"))
        assert scene.monitored is True


def test_monitored_discovery_isolates_changed_scene_writes_off_event_loop():
    source = (ROOT / "scarletx" / "monitored_entities.py").read_text(encoding="utf-8")
    compact = "".join(source.split())
    helper_start = compact.index("def_persist_discovered_scenes(")
    helper_end = compact.index("asyncdefmonitored_entity_discovery_cycle", helper_start)
    persistence = compact[helper_start:helper_end]
    assert 'upsert_scene(db,remote,monitored=True,content_type="scene",commit=False)' in persistence
    assert "SCENE_WRITE_MAX_ATTEMPTS=3" in compact
    assert "failed_remote_ids" in persistence
    assert "_is_sqlite_locked_error(exc)" in persistence
    assert "awaitasyncio.to_thread(_persist_discovered_scenes" in compact


def test_upsert_scene_supports_deferred_commit():
    source = (ROOT / "scarletx" / "services.py").read_text(encoding="utf-8")
    assert "commit: bool = True" in source
    assert "if commit:" in source
