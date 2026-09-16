from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from scarletx.models import Base, History, MediaFile, Scene


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _scene(db):
    scene = Scene(tpdb_id="upgrade-scene", title="Upgrade Scene", content_type="scene")
    db.add(scene)
    db.flush()
    return scene


def test_unverified_candidate_preserves_existing_media(tmp_path):
    from scarletx.upgrade_transaction import finalize_verified_upgrade

    Session = _session()
    old_path = tmp_path / "old.mkv"
    new_path = tmp_path / "new.mkv"
    old_path.write_bytes(b"old")
    new_path.write_bytes(b"new")

    with Session() as db:
        scene = _scene(db)
        old = MediaFile(scene_id=scene.id, path=str(old_path), size_bytes=3)
        new = MediaFile(scene_id=scene.id, path=str(new_path), size_bytes=3)
        db.add_all([old, new])
        db.commit()
        old_id = old.id
        new_id = new.id

    with Session() as db:
        retired = finalize_verified_upgrade(
            db,
            new_media_id=new_id,
            previous_media_ids=[old_id],
            verified=False,
        )
        db.commit()
        assert retired == 0
        assert db.get(MediaFile, old_id) is not None
        assert db.get(MediaFile, new_id) is not None

    assert old_path.exists()
    assert new_path.exists()


def test_verified_candidate_retires_old_and_records_history(tmp_path):
    from scarletx.upgrade_transaction import finalize_verified_upgrade

    Session = _session()
    old_path = tmp_path / "old.mkv"
    new_path = tmp_path / "new.mkv"
    old_path.write_bytes(b"old")
    new_path.write_bytes(b"better")

    with Session() as db:
        scene = _scene(db)
        old = MediaFile(scene_id=scene.id, path=str(old_path), size_bytes=3)
        new = MediaFile(scene_id=scene.id, path=str(new_path), size_bytes=6)
        db.add_all([old, new])
        db.commit()
        old_id = old.id
        new_id = new.id

    with Session() as db:
        retired = finalize_verified_upgrade(
            db,
            new_media_id=new_id,
            previous_media_ids=[old_id],
            verified=True,
        )
        db.commit()
        assert retired == 1
        assert db.get(MediaFile, old_id) is None
        assert db.get(MediaFile, new_id) is not None
        event = db.scalar(select(History).where(History.event_type == "media_upgraded"))
        assert event is not None

    assert not old_path.exists()
    assert new_path.exists()


def test_failed_candidate_rolls_back_without_touching_previous_media(tmp_path):
    from scarletx.upgrade_transaction import rollback_upgrade_candidate

    Session = _session()
    old_path = tmp_path / "old.mkv"
    new_path = tmp_path / "candidate.mkv"
    old_path.write_bytes(b"old")
    new_path.write_bytes(b"bad")

    with Session() as db:
        scene = _scene(db)
        old = MediaFile(scene_id=scene.id, path=str(old_path), size_bytes=3)
        new = MediaFile(scene_id=scene.id, path=str(new_path), size_bytes=3)
        db.add_all([old, new])
        db.commit()
        old_id = old.id
        new_id = new.id

    with Session() as db:
        rollback_upgrade_candidate(db, new_media_id=new_id, reason="probe failed")
        db.commit()
        assert db.get(MediaFile, old_id) is not None
        assert db.get(MediaFile, new_id) is None
        event = db.scalar(
            select(History).where(History.event_type == "media_upgrade_rolled_back")
        )
        assert event is not None

    assert old_path.exists()
    assert not new_path.exists()


def test_download_processing_requires_probe_success_before_upgrade_retirement():
    source = Path("scarletx/download_processing.py").read_text()
    assert "finalize_verified_upgrade" in source
    assert "rollback_upgrade_candidate" in source
    verification = source.index("index_media_file_by_id")
    finalize = source.index("finalize_verified_upgrade", verification)
    assert verification < finalize
