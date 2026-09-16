from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.db import Base
from scarletx.models import Scene
from scarletx.bulk_operations import BulkWantedRequest, bulk_wanted


ROOT = Path(__file__).resolve().parents[1]


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_bulk_unmonitor_is_idempotent_and_deduplicates_ids():
    factory = _session_factory()
    with factory() as db:
        scene = Scene(tpdb_id="bulk-1", title="Bulk One", content_type="scene", monitored=True)
        db.add(scene)
        db.commit()
        scene_id = scene.id

        result = await bulk_wanted(
            BulkWantedRequest(action="unmonitor", scene_ids=[scene_id, scene_id]),
            db=db,
        )

        assert result["requested"] == 1
        assert result["processed"] == 1
        assert result["action"] == "unmonitor"
        db.refresh(scene)
        assert scene.monitored is False


@pytest.mark.asyncio
async def test_bulk_search_only_runs_selected_scenes_once(monkeypatch):
    factory = _session_factory()
    calls: list[int] = []

    class Result:
        def __init__(self, scene_id: int):
            self.scene_id = scene_id

        def as_dict(self):
            return {"scene_id": self.scene_id, "status": "queued"}

    async def fake_search(_factory, scene_id, _settings):
        calls.append(scene_id)
        return Result(scene_id)

    monkeypatch.setattr("scarletx.bulk_operations.search_and_grab_scene", fake_search)
    monkeypatch.setattr("scarletx.bulk_operations.load_database_settings", lambda _db: object())

    with factory() as db:
        one = Scene(tpdb_id="bulk-2", title="Bulk Two", content_type="scene", monitored=True)
        two = Scene(tpdb_id="bulk-3", title="Bulk Three", content_type="scene", monitored=True)
        db.add_all([one, two])
        db.commit()

        result = await bulk_wanted(
            BulkWantedRequest(action="search", scene_ids=[one.id, two.id, one.id]),
            db=db,
        )

    assert calls == [one.id, two.id]
    assert result["requested"] == 2
    assert result["processed"] == 2
    assert [row["scene_id"] for row in result["results"]] == [one.id, two.id]


def test_bulk_request_is_bounded_to_25_scene_ids():
    with pytest.raises(ValidationError):
        BulkWantedRequest(action="search", scene_ids=list(range(1, 27)))


def test_composed_app_registers_bulk_route_once():
    from scarletx.app import app

    routes = [
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/wanted/bulk"
        and "POST" in (getattr(route, "methods", set()) or set())
    ]
    assert len(routes) == 1


def test_wanted_bulk_ui_is_packaged_and_uses_bounded_selected_actions():
    source = (ROOT / "frontend" / "wanted_bulk_overrides.js").read_text(encoding="utf-8")
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")

    assert "/api/wanted/bulk" in source
    assert "Search Selected" in source
    assert "Unmonitor Selected" in source
    assert "data-wanted-select" in source
    assert "slice(0, 25)" in source
    assert '<script src="/wanted_bulk_overrides.js"></script>' in index
    assert "COPY frontend/wanted_bulk_overrides.js" in dockerfile
