from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.db import Base
from scarletx.models import Scene, Studio, TrackedDownload
from scarletx.routes.application import _tracked_download_rows

ROOT = Path(__file__).resolve().parents[1]


def test_tracked_download_rows_include_scene_studio_name():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    with Session() as db:
        studio = Studio(tpdb_id="studio-1", name="Studio One", monitored=True, is_library=True)
        scene = Scene(tpdb_id="scene-1", title="Scene One", studio=studio, monitored=True)
        db.add_all([studio, scene])
        db.flush()
        tracked = TrackedDownload(
            nzo_id="job-1",
            release_title="Studio.One.Scene.One.1080p",
            scene_id=scene.id,
            scene_tpdb_id=scene.tpdb_id,
            scene_title=scene.title,
            status="queued",
        )
        db.add(tracked)
        db.commit()

        row = _tracked_download_rows(db, [tracked])[0]

    assert row["studio"] == "Studio One"


def test_downloads_frontend_renders_studio_beneath_title():
    source = (ROOT / "frontend" / "activity_studio_overrides.js").read_text(encoding="utf-8")

    assert "live-studio" in source
    assert "x.studio" in source
    assert "activityQueueHtml" in source
