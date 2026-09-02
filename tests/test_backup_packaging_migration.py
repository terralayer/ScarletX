from pathlib import Path


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
