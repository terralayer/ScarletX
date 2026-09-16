from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.db import Base
from scarletx.models import History, Scene, TrackedDownload
from scarletx.wanted import missing_items


def _factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _scene(identifier: str, title: str) -> Scene:
    return Scene(
        tpdb_id=identifier,
        title=title,
        content_type="scene",
        release_date=date(2026, 1, 1),
        monitored=True,
    )


def test_wanted_distinguishes_never_searched_and_no_result():
    factory = _factory()
    with factory() as db:
        never = _scene("never", "Never Searched")
        empty = _scene("empty", "No Results")
        db.add_all([never, empty])
        db.flush()
        db.add(
            History(
                event_type="scene_monitor_search",
                scene_id=empty.id,
                message="Immediate monitor search for No Results: no_match",
            )
        )
        db.commit()

        rows = {row["metadata_id"]: row for row in missing_items(db)}

    assert rows["never"]["state"] == "never_searched"
    assert rows["never"]["reason"] == "Never searched"
    assert rows["never"]["last_search_at"] is None
    assert rows["never"]["result_count"] is None
    assert rows["never"]["active"] is False

    assert rows["empty"]["state"] == "no_result"
    assert rows["empty"]["reason"] == "Search returned no downloadable release"
    assert rows["empty"]["last_search_at"] is not None
    assert rows["empty"]["result_count"] == 0
    assert rows["empty"]["active"] is False


def test_wanted_distinguishes_active_download_and_failed_import():
    factory = _factory()
    with factory() as db:
        active = _scene("active", "Active Download")
        failed = _scene("failed", "Failed Import")
        db.add_all([active, failed])
        db.flush()
        db.add_all(
            [
                TrackedDownload(
                    nzo_id="active-1",
                    release_title="Active.Download.1080p",
                    scene_id=active.id,
                    scene_tpdb_id=active.tpdb_id,
                    scene_title=active.title,
                    status="downloading",
                    client_status="downloading",
                ),
                TrackedDownload(
                    nzo_id="failed-1",
                    release_title="Failed.Import.1080p",
                    scene_id=failed.id,
                    scene_tpdb_id=failed.tpdb_id,
                    scene_title=failed.title,
                    status="failed",
                    client_status="failed",
                    error="Import failed (attempt 3/3): probe rejected truncated media",
                ),
            ]
        )
        db.commit()

        rows = {row["metadata_id"]: row for row in missing_items(db)}

    assert rows["active"]["state"] == "downloading"
    assert rows["active"]["active"] is True
    assert rows["active"]["result_count"] == 1
    assert "Download" in rows["active"]["reason"]

    assert rows["failed"]["state"] == "failed_import"
    assert rows["failed"]["active"] is False
    assert rows["failed"]["result_count"] == 1
    assert "Import failed" in rows["failed"]["reason"]
