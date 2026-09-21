from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from scarletx.db import Base
from scarletx.library_reset import reset_library
from scarletx.models import (
    AppSetting,
    History,
    IndexerFeedItem,
    LibraryItemConfig,
    MediaFile,
    MediaProbe,
    PlaybackState,
    Performer,
    QualityProfile,
    ReleaseBlocklist,
    RootFolder,
    Scene,
    Studio,
    Tag,
    TrackedDownload,
    UserTag,
    library_user_tag,
)


def test_start_over_deletes_library_and_media_but_preserves_configuration_and_history(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'start-over.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    media_root = tmp_path / "media"
    media_root.mkdir()
    media_path = media_root / "scene.mp4"
    media_path.write_bytes(b"video")
    unrelated = media_root / "not-indexed.txt"
    unrelated.write_text("keep", encoding="utf-8")
    generated_root = tmp_path / "generated"
    generated_media = generated_root / "media" / "1"
    generated_media.mkdir(parents=True)
    (generated_media / "preview.mp4").write_bytes(b"preview")

    with factory() as db:
        studio = Studio(tpdb_id="studio-1", name="Studio", is_library=True)
        performer = Performer(tpdb_id="performer-1", name="Performer", is_library=True)
        tag = Tag(tpdb_id="tag-1", name="Tag")
        user_tag = UserTag(name="favorite", label="Favorite")
        scene = Scene(
            tpdb_id="scene-1",
            title="Scene",
            content_type="scene",
            release_date=date(2026, 1, 1),
            studio=studio,
        )
        scene.performers.append(performer)
        scene.tags.append(tag)
        root = RootFolder(name="Scenes", content_type="scene", path=str(media_root), is_default=True)
        profile = QualityProfile(name="HD", is_default=True)
        db.add_all([scene, root, profile, user_tag, AppSetting(key="keep", value="yes")])
        db.flush()
        db.execute(library_user_tag.insert().values(scene_id=scene.id, tag_id=user_tag.id))
        media = MediaFile(scene_id=scene.id, path=str(media_path), size_bytes=5)
        db.add(media)
        db.flush()
        db.add_all([
            MediaProbe(media_file_id=media.id, missing=False),
            PlaybackState(media_file_id=media.id, favorite=True),
            LibraryItemConfig(scene_id=scene.id, root_folder_id=root.id, quality_profile_id=profile.id),
            History(event_type="import", scene_id=scene.id, message="Imported"),
            IndexerFeedItem(indexer="indexer", guid="guid", title="Release", scene_id=scene.id),
            ReleaseBlocklist(release_title="Release", scene_id=scene.id, reason="Failed"),
            TrackedDownload(nzo_id="download-1", release_title="Release", scene_id=scene.id),
        ])
        db.commit()
        media_id = media.id
        scene_id = scene.id

        result = reset_library(db, root_paths=[media_root], generated_root=generated_root)

        assert result == {
            "media_files": 1,
            "files_deleted": 1,
            "files_skipped": 0,
            "scenes": 1,
            "performers": 1,
            "studios": 1,
        }
        assert not media_path.exists()
        assert not generated_media.exists()
        assert unrelated.exists()
        assert db.get(MediaFile, media_id) is None
        assert db.get(MediaProbe, media_id) is None
        assert db.get(PlaybackState, media_id) is None
        assert db.get(Scene, scene_id) is None
        assert db.scalars(select(Performer)).all() == []
        assert db.scalars(select(Studio)).all() == []
        assert db.scalars(select(Tag)).all() == []
        assert db.scalars(select(UserTag)).all() == []
        assert db.scalars(select(LibraryItemConfig)).all() == []
        assert db.scalar(select(AppSetting.value).where(AppSetting.key == "keep")) == "yes"
        assert db.get(RootFolder, root.id) is not None
        assert db.get(QualityProfile, profile.id) is not None
        assert db.scalar(select(History.scene_id)) is None
        assert db.scalar(select(IndexerFeedItem.scene_id)) is None
        assert db.scalar(select(ReleaseBlocklist.scene_id)) is None
        assert db.scalar(select(TrackedDownload.scene_id)) is None

    engine.dispose()
