from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace


def _scene(identifier, title, *, studio=None, release_date=None, performers=()):
    return SimpleNamespace(
        id=identifier,
        title=title,
        studio=SimpleNamespace(name=studio) if studio else None,
        release_date=release_date,
        performers=[SimpleNamespace(name=name) for name in performers],
    )


def test_exact_unique_title_is_exact_confidence():
    from scarletx.library_match import build_scene_match_index, rank_local_scene

    scene = _scene(1, "A Perfect Scene")
    result = rank_local_scene(Path("A.Perfect.Scene.mkv"), build_scene_match_index([scene]))

    assert result.scene is scene
    assert result.confidence == "exact"
    assert result.auto_match is True
    assert result.score >= 100


def test_title_plus_studio_and_date_is_high_confidence():
    from scarletx.library_match import build_scene_match_index, rank_local_scene

    scene = _scene(
        2,
        "Private Lesson",
        studio="Example Studio",
        release_date=date(2026, 4, 18),
    )
    result = rank_local_scene(
        Path("Example.Studio.Private.Lesson.2026.04.18.1080p.mkv"),
        build_scene_match_index([scene]),
    )

    assert result.scene is scene
    assert result.confidence == "high"
    assert result.auto_match is True
    assert "studio" in result.reasons
    assert "release_date" in result.reasons


def test_title_only_match_is_medium_and_not_automatic():
    from scarletx.library_match import build_scene_match_index, match_local_scene, rank_local_scene

    scene = _scene(3, "Unique Long Scene Title")
    index = build_scene_match_index([scene])
    path = Path("Unique.Long.Scene.Title.1080p.WEB-DL.mkv")

    result = rank_local_scene(path, index)
    assert result.scene is scene
    assert result.confidence == "medium"
    assert result.auto_match is False
    assert match_local_scene(path, index) is None


def test_performer_overlap_can_promote_title_match_to_high_confidence():
    from scarletx.library_match import build_scene_match_index, rank_local_scene

    scene = _scene(4, "Late Checkout", performers=("Alex Example", "Jamie Sample"))
    result = rank_local_scene(
        Path("Late.Checkout.Alex.Example.1080p.mkv"),
        build_scene_match_index([scene]),
    )

    assert result.scene is scene
    assert result.confidence == "high"
    assert result.auto_match is True
    assert "performer" in result.reasons


def test_equal_candidates_are_ambiguous_and_never_automatic():
    from scarletx.library_match import build_scene_match_index, rank_local_scene

    first = _scene(5, "Shared Title")
    second = _scene(6, "Shared Title")
    result = rank_local_scene(Path("Shared.Title.mkv"), build_scene_match_index([first, second]))

    assert result.scene is None
    assert result.confidence == "ambiguous"
    assert result.auto_match is False
    assert set(result.candidate_ids) == {5, 6}
