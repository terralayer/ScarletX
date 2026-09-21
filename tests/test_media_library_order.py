from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.db import Base
from scarletx.models import MediaFile, Scene
from scarletx.routes.application import media_library_files_page


def _session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_media_library_pages_order_newest_release_first_across_cursor_pages():
    db = _session()
    imported = datetime(2026, 9, 20, tzinfo=timezone.utc)
    newest = Scene(tpdb_id="newest", title="Newest release", content_type="scene", release_date=date(2026, 9, 20))
    middle = Scene(tpdb_id="middle", title="Middle release", content_type="scene", release_date=date(2026, 9, 10))
    oldest = Scene(tpdb_id="oldest", title="Oldest release", content_type="scene", release_date=date(2026, 9, 1))
    undated = Scene(tpdb_id="undated", title="Undated release", content_type="scene")
    db.add_all([
        newest,
        middle,
        oldest,
        undated,
    ])
    db.flush()
    db.add_all([
        MediaFile(scene_id=newest.id, path="/media/newest.mp4", imported_at=imported),
        MediaFile(scene_id=middle.id, path="/media/middle.mp4", imported_at=imported + timedelta(days=1)),
        MediaFile(scene_id=oldest.id, path="/media/oldest.mp4", imported_at=imported + timedelta(days=2)),
        MediaFile(scene_id=undated.id, path="/media/undated.mp4", imported_at=imported + timedelta(days=3)),
    ])
    db.commit()

    first = media_library_files_page(limit=2, cursor=None, db=db)
    second = media_library_files_page(limit=2, cursor=first["next_cursor"], db=db)

    assert [item["scene_title"] for item in first["items"]] == ["Newest release", "Middle release"]
    assert [item["scene_title"] for item in second["items"]] == ["Oldest release", "Undated release"]
