from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scarletx.db import Base
from scarletx.list_queries import studio_summary_page
from scarletx.models import MediaFile, Scene, Studio


ROOT = Path(__file__).resolve().parents[1]


def _factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'studio-counts.db'}")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_studio_summary_reports_downloaded_and_total_scene_counts(tmp_path):
    engine, factory = _factory(tmp_path)
    with factory() as db:
        studio = Studio(tpdb_id="studio-counts", name="Count Studio", is_library=True)
        db.add(studio)
        db.flush()
        downloaded = Scene(
            tpdb_id="downloaded",
            title="Downloaded",
            content_type="scene",
            studio_id=studio.id,
        )
        missing = Scene(
            tpdb_id="missing",
            title="Missing",
            content_type="scene",
            studio_id=studio.id,
        )
        non_scene = Scene(
            tpdb_id="non-scene",
            title="Non-scene",
            content_type="movie",
            studio_id=studio.id,
        )
        db.add_all([downloaded, missing, non_scene])
        db.flush()
        db.add_all(
            [
                MediaFile(scene_id=downloaded.id, path=str(tmp_path / "one.mp4")),
                MediaFile(scene_id=downloaded.id, path=str(tmp_path / "two.mp4")),
            ]
        )
        db.commit()

        item = studio_summary_page(db, limit=10)["items"][0]
        assert item["downloaded_scene_count"] == 1
        assert item["scene_count"] == 2
    engine.dispose()
