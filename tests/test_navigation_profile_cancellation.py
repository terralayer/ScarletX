from pathlib import Path


ROOT = Path(__file__).parents[1]
APP = ROOT / "frontend" / "app.js"


def _section(source: str, start: str, end: str) -> str:
    return source[source.index(start):source.index(end)]


def test_profile_scene_pagination_stops_when_navigation_is_stale():
    source = APP.read_text(encoding="utf-8")

    performer_loader = _section(
        source,
        "async function loadAllPerformerScenes",
        "async function loadAllStudioScenes",
    )
    studio_loader = _section(
        source,
        "async function loadAllStudioScenes",
        "function localPerformerProfile",
    )
    performer_profile = _section(
        source,
        "async function performerProfile",
        "async function studioProfile",
    )
    studio_profile = _section(
        source,
        "async function studioProfile",
        "async function openLocalScene",
    )

    assert "generation" in performer_loader.split("{")[0]
    assert "generation" in studio_loader.split("{")[0]
    assert "navigationGenerationCurrent(generation)" in performer_loader
    assert "navigationGenerationCurrent(generation)" in studio_loader
    assert "loadAllPerformerScenes(id,resolvedLocalId,generation)" in performer_profile.replace(" ", "")
    assert "loadAllStudioScenes(id,resolvedLocalId,generation)" in studio_profile.replace(" ", "")
