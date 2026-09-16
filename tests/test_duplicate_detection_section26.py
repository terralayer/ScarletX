from __future__ import annotations

from types import SimpleNamespace


def test_matching_source_guid_or_content_hash_is_exact_duplicate():
    from scarletx.duplicate_policy import DuplicateEvidence, classify_duplicate

    first = DuplicateEvidence(tpdb_id="scene-1", source_guid="nzb-123")
    second = DuplicateEvidence(tpdb_id="scene-1", source_guid="nzb-123")
    assert classify_duplicate(first, second).classification == "duplicate"
    assert classify_duplicate(first, second).automatic is True

    first = DuplicateEvidence(tpdb_id="scene-1", content_hash="abc")
    second = DuplicateEvidence(tpdb_id="scene-1", content_hash="abc")
    assert classify_duplicate(first, second).classification == "duplicate"
    assert classify_duplicate(first, second).automatic is True


def test_conflicting_tpdb_identity_is_distinct_even_when_size_and_duration_match():
    from scarletx.duplicate_policy import DuplicateEvidence, classify_duplicate

    first = DuplicateEvidence(
        tpdb_id="scene-1",
        size_bytes=2_000_000_000,
        duration_seconds=1200.0,
    )
    second = DuplicateEvidence(
        tpdb_id="scene-2",
        size_bytes=2_000_000_000,
        duration_seconds=1200.0,
    )
    result = classify_duplicate(first, second)
    assert result.classification == "distinct"
    assert result.automatic is False


def test_same_scene_similar_size_and_duration_is_review_not_auto_delete():
    from scarletx.duplicate_policy import DuplicateEvidence, classify_duplicate

    first = DuplicateEvidence(
        tpdb_id="scene-1",
        size_bytes=2_000_000_000,
        duration_seconds=1200.0,
    )
    second = DuplicateEvidence(
        tpdb_id="scene-1",
        size_bytes=2_010_000_000,
        duration_seconds=1200.8,
    )
    result = classify_duplicate(first, second)
    assert result.classification == "review"
    assert result.automatic is False
    assert "size_duration" in result.reasons


def test_material_size_or_duration_difference_is_distinct():
    from scarletx.duplicate_policy import DuplicateEvidence, classify_duplicate

    first = DuplicateEvidence(
        tpdb_id="scene-1",
        size_bytes=2_000_000_000,
        duration_seconds=1200.0,
    )
    second = DuplicateEvidence(
        tpdb_id="scene-1",
        size_bytes=3_000_000_000,
        duration_seconds=1600.0,
    )
    assert classify_duplicate(first, second).classification == "distinct"


def test_full_hash_is_not_used_without_a_quick_fingerprint_collision(tmp_path, monkeypatch):
    import scarletx.media_dedup as dedup

    paths = []
    for index, payload in enumerate((b"aaaa", b"bbbb", b"cccc")):
        path = tmp_path / f"{index}.mkv"
        path.write_bytes(payload)
        paths.append(path)
    rows = [
        SimpleNamespace(id=index + 1, path=str(path), size_bytes=4)
        for index, path in enumerate(paths)
    ]

    quick = iter(("one", "two", "three"))
    monkeypatch.setattr(dedup, "_quick_fingerprint", lambda _path: next(quick))
    calls = []
    monkeypatch.setattr(dedup, "full_sha256", lambda path: calls.append(path) or path.name)

    assert dedup._verified_duplicate_groups(rows) == []
    assert calls == []
