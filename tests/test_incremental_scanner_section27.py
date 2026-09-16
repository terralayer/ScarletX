from __future__ import annotations

from pathlib import Path


def test_load_states_filters_in_sql_instead_of_reading_entire_table(tmp_path):
    from scarletx.library_scanner import load_states

    statements = []

    class Result:
        def all(self):
            return []

    class Database:
        def scalars(self, statement):
            statements.append(str(statement))
            return Result()

    load_states(Database(), [tmp_path / "dirty"])

    assert len(statements) == 1
    assert "WHERE" in statements[0].upper()
    assert "path" in statements[0].casefold()


def test_manual_full_scan_uses_configured_roots_not_dirty_scope(monkeypatch, tmp_path):
    import scarletx.media_library as media_library
    from scarletx.library_scanner import scan_directories

    calls = []

    def fake_scan_library(session_factory, directories=None):
        calls.append((session_factory, directories))
        return {"processed": 0}

    monkeypatch.setattr(media_library, "scan_library", fake_scan_library)
    factory = object()
    dirty = [Path(tmp_path) / "dirty"]

    assert scan_directories(factory, dirty, full=True) == {"processed": 0}
    assert calls == [(factory, None)]


def test_incremental_scan_keeps_explicit_dirty_scope(monkeypatch, tmp_path):
    import scarletx.media_library as media_library
    from scarletx.library_scanner import scan_directories

    calls = []

    def fake_scan_library(session_factory, directories=None):
        calls.append((session_factory, directories))
        return {"processed": 0}

    monkeypatch.setattr(media_library, "scan_library", fake_scan_library)
    factory = object()
    dirty = [Path(tmp_path) / "dirty-a", Path(tmp_path) / "dirty-b"]

    assert scan_directories(factory, dirty, full=False) == {"processed": 0}
    assert calls == [(factory, dirty)]
