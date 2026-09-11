from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.db import Base
from scarletx.models import Performer, Scene, scene_performer
from scarletx.schemas import RemotePerson, RemoteScene, RemoteStudio, SearchResponse
from scarletx.wanted import calendar_items

ROOT = Path(__file__).resolve().parents[1]


def make_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_entity_requests_use_page_local_sequence_not_global_navigation_generation():
    source = (ROOT / "frontend" / "navigation_error_overrides.js").read_text(encoding="utf-8")
    compact = "".join(source.split())
    assert "entityRequestGeneration" in source
    assert "functionnextEntityRequest(type)" in compact
    assert "functionentityRequestCurrent(type,generation)" in compact
    assert "loadEntityLibrary=asyncfunction" in compact
    assert "searchEntity=asyncfunction" in compact
    assert "entityRequestCurrent(type,generation)" in compact
    assert "navigationGenerationCurrent(generation)" not in compact[compact.index("loadEntityLibrary=asyncfunction"):]


def test_top_left_x_mark_is_removed_but_brand_word_remains():
    source = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert 'class="brandmark"' not in source
    assert 'class="brandword">Scarlet<b>X</b>' in source


def test_scene_and_library_studio_art_is_large_enough_to_read():
    styles = (ROOT / "frontend" / "ui_overrides.css").read_text(encoding="utf-8")
    compact = "".join(styles.split())
    assert ".studio-logo{width:72px;height:40px;flex:0072px" in compact
    assert ".studio-logoimg{width:100%;height:100%;object-fit:contain" in compact


def test_calendar_includes_future_scene_via_monitored_performer_relationship():
    factory = make_factory()
    future = date.today() + timedelta(days=14)
    with factory() as db:
        performer = Performer(tpdb_id="p1", name="P1", monitored=True, is_library=True)
        scene = Scene(tpdb_id="s1", title="Coming Soon", content_type="scene", monitored=False, release_date=future)
        db.add_all([performer, scene])
        db.flush()
        db.execute(scene_performer.insert().values(scene_id=scene.id, performer_id=performer.id))
        db.commit()
        items = calendar_items(db, date.today(), date.today() + timedelta(days=90))
    assert [item["title"] for item in items] == ["Coming Soon"]


class UnchangedMetadata:
    def __init__(self):
        self.scene = RemoteScene(
            id="existing-future",
            title="Existing Future",
            release_date=date.today() + timedelta(days=10),
            studio=RemoteStudio(id="studio-1", search_id=77, name="Studio One"),
            performers=[RemotePerson(id="person-1", search_id=10, name="Performer One")],
        )

    async def get_performer_scenes(self, identifier, page=1, per_page=48):
        return SearchResponse(items=[self.scene] if page == 1 else [], total=1, page=page, per_page=per_page)

    async def get_studio(self, identifier):
        return RemoteStudio(id="studio-1", search_id=77, name="Studio One")

    async def search_scenes(self, query=None, page=1, per_page=48, performer_id=None, site_id=None):
        return SearchResponse(items=[self.scene] if page == 1 else [], total=1, page=page, per_page=per_page)


@pytest.mark.asyncio
async def test_hourly_discovery_promotes_existing_related_scene_to_monitored(monkeypatch):
    from scarletx import monitored_entities

    factory = make_factory()
    with factory() as db:
        performer = Performer(tpdb_id="person-1", name="Performer One", monitored=True, is_library=True)
        scene = Scene(
            tpdb_id="existing-future",
            title="Existing Future",
            content_type="scene",
            monitored=False,
            release_date=date.today() + timedelta(days=10),
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


def test_monitored_discovery_batches_scene_upserts_in_one_session():
    source = (ROOT / "scarletx" / "monitored_entities.py").read_text(encoding="utf-8")
    compact = "".join(source.split())
    assert 'upsert_scene(db,remote,monitored=True,content_type="scene",commit=False)' in compact
    batch_start = compact.index("withsession_factory()asdb:forremoteindiscovered.values():")
    batch_end = compact.index("return{", batch_start)
    batch = compact[batch_start:batch_end]
    assert batch.count("db.commit()") == 1


def test_upsert_scene_supports_deferred_commit():
    source = (ROOT / "scarletx" / "services.py").read_text(encoding="utf-8")
    assert "commit: bool = True" in source
    assert "if commit:" in source
