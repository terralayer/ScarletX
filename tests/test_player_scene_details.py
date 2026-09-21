from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scarletx.db import Base
from scarletx.media_library import media_row
from scarletx.models import MediaFile, MediaProbe, Performer, Scene, Studio, Tag


def test_player_detail_includes_linked_scene_metadata(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    media_path = tmp_path / "scene.mp4"
    media_path.write_bytes(b"video")

    with Session() as db:
        studio = Studio(tpdb_id="studio-1", name="Scarlet Studio")
        performer = Performer(tpdb_id="performer-1", name="Alex Example")
        tag = Tag(tpdb_id="tag-1", name="Behind the Scenes")
        scene = Scene(
            tpdb_id="scene-1",
            title="A Scene",
            description="A complete scene description.",
            release_date=date(2026, 9, 19),
            studio=studio,
        )
        scene.performers.append(performer)
        scene.tags.append(tag)
        media = MediaFile(scene=scene, path=str(media_path), size_bytes=5)
        db.add_all([scene, media])
        db.commit()

        detail = media_row(db, media)

    assert detail["description"] == "A complete scene description."
    assert detail["studio"] == "Scarlet Studio"
    assert detail["release_date"] == date(2026, 9, 19)
    assert detail["performers"] == [{"id": "performer-1", "name": "Alex Example"}]
    assert detail["tags"] == ["Behind the Scenes"]


def test_player_renders_scene_details_below_the_video():
    source = (__import__("pathlib").Path(__file__).resolve().parents[1] / "frontend" / "app.js").read_text(encoding="utf-8")

    player = source[source.index("function playerSceneDetails"):source.index("const WANTED_PAGE_SIZE")]
    assert '<div class="player-shell"><video' in player
    assert "Scene Details" in player
    assert "x.description" in player
    assert "x.performers" in player
    assert "x.tags" in player
    assert "${playerSceneDetails(x)}" in player


def test_scene_info_includes_a_play_action_when_the_scene_has_media():
    source = (__import__("pathlib").Path(__file__).resolve().parents[1] / "frontend" / "app.js").read_text(encoding="utf-8")

    scene = source[source.index("async function scenePage"):source.index("async function remoteDetail")]
    assert 'id="playSceneInfo"' in scene
    assert "$('#playSceneInfo').onclick" in scene


def test_media_detail_marks_a_missing_source_file_as_missing_even_with_an_old_probe(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    with Session() as db:
        scene = Scene(tpdb_id="scene-missing", title="Missing source")
        media = MediaFile(scene=scene, path=str(tmp_path / "gone.mp4"))
        db.add_all([scene, media])
        db.commit()
        db.add(MediaProbe(media_file_id=media.id, missing=False))
        db.commit()

        assert media_row(db, media)["missing"] is True
