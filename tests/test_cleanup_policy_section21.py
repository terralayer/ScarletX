from __future__ import annotations

from datetime import UTC, datetime, timedelta


def test_failed_import_preserves_native_staging(tmp_path):
    from scarletx.cleanup_policy import cleanup_native_staging

    staging = tmp_path / "incomplete" / "job-1"
    staging.mkdir(parents=True)
    payload = staging / "scene.mkv"
    payload.write_bytes(b"video")

    removed = cleanup_native_staging(
        staging,
        library_path=tmp_path / "library" / "scene.mkv",
        import_succeeded=False,
    )

    assert removed is False
    assert payload.exists()


def test_successful_import_removes_owned_staging_outside_library(tmp_path):
    from scarletx.cleanup_policy import cleanup_native_staging

    staging = tmp_path / "complete" / "job-2"
    staging.mkdir(parents=True)
    (staging / "support.par2").write_bytes(b"par")
    library = tmp_path / "library" / "scene.mkv"
    library.parent.mkdir()
    library.write_bytes(b"video")

    removed = cleanup_native_staging(staging, library_path=library, import_succeeded=True)

    assert removed is True
    assert not staging.exists()
    assert library.exists()


def test_cleanup_never_deletes_directory_that_contains_library_file(tmp_path):
    from scarletx.cleanup_policy import cleanup_native_staging

    staging = tmp_path / "library" / "job-3"
    staging.mkdir(parents=True)
    library = staging / "scene.mkv"
    library.write_bytes(b"video")

    removed = cleanup_native_staging(staging, library_path=library, import_succeeded=True)

    assert removed is False
    assert library.exists()


def test_orphan_partial_cleanup_is_name_and_age_scoped(tmp_path):
    from scarletx.cleanup_policy import cleanup_orphan_partials

    now = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    old_partial = tmp_path / ".scene.mkv.partial-deadbeef"
    fresh_partial = tmp_path / ".fresh.mkv.partial-cafe"
    ordinary = tmp_path / "scene.mkv"
    for path in (old_partial, fresh_partial, ordinary):
        path.write_bytes(b"x")

    import os

    old = (now - timedelta(days=2)).timestamp()
    fresh = (now - timedelta(hours=1)).timestamp()
    os.utime(old_partial, (old, old))
    os.utime(fresh_partial, (fresh, fresh))

    removed = cleanup_orphan_partials(tmp_path, older_than=timedelta(days=1), now=now)

    assert removed == [old_partial]
    assert not old_partial.exists()
    assert fresh_partial.exists()
    assert ordinary.exists()
