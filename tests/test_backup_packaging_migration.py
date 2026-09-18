def test_legacy_default_uses_packaged_backup_override(monkeypatch, tmp_path):
    from scarletx.backups import _backup_dir

    packaged = tmp_path / "persistent-backups"
    monkeypatch.setenv("SCARLETX_BACKUP_DIR", str(packaged))

    assert _backup_dir("./backups") == packaged
    assert packaged.is_dir()


def test_custom_backup_directory_is_not_overridden(monkeypatch, tmp_path):
    from scarletx.backups import _backup_dir

    packaged = tmp_path / "persistent-backups"
    custom = tmp_path / "custom-backups"
    monkeypatch.setenv("SCARLETX_BACKUP_DIR", str(packaged))

    assert _backup_dir(str(custom)) == custom
    assert custom.is_dir()
    assert not packaged.exists()


def test_backups_created_at_the_same_instant_use_distinct_files(monkeypatch, tmp_path):
    from datetime import UTC, datetime
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from scarletx import backups
    from scarletx.models import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'source.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(backups, "engine", engine)
    monkeypatch.setattr(backups, "_copy_secret_key_for_backup", lambda path: None)

    class FixedClock:
        @staticmethod
        def now(tz):
            return datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(backups, "datetime", FixedClock)
    with Session(engine) as db:
        first = backups.create_backup(db, str(tmp_path / "backups"))
        first_path = first.path
        second = backups.create_backup(db, str(tmp_path / "backups"))
        assert first_path != second.path
        assert len(list((tmp_path / "backups").glob("*.db"))) == 2
    engine.dispose()
