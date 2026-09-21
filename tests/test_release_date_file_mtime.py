from datetime import UTC, date, datetime, time
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scarletx.config import Settings
from scarletx.db import Base
from scarletx.library_management import import_specific_media_file
from scarletx.models import MediaFile, RootFolder, Scene


def test_imported_media_file_modified_date_matches_scene_release_date(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'release-date.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    media_root = tmp_path / "media"
    media_root.mkdir()
    source = tmp_path / "download.mp4"
    source.write_bytes(b"video")
    release_date = date(2024, 2, 3)

    with factory() as db:
        scene = Scene(
            tpdb_id="release-date-scene",
            title="Release Date Scene",
            content_type="scene",
            release_date=release_date,
        )
        db.add(scene)
        db.flush()
        db.add(
            RootFolder(
                name="Scenes",
                content_type="scene",
                path=str(media_root),
                is_default=True,
                create_missing=True,
            )
        )
        db.commit()

        media = import_specific_media_file(
            db,
            scene=scene,
            source=source,
            release_title="Release Date Scene",
            settings=Settings(
                scene_naming_template="{Title}",
                import_mode="copy",
                minimum_free_space_gb=0,
            ),
        )
        db.commit()

        expected = datetime.combine(release_date, time(12), tzinfo=UTC).timestamp()
        assert abs(Path(media.path).stat().st_mtime - expected) < 1
        assert db.get(MediaFile, media.id) is not None

    engine.dispose()
