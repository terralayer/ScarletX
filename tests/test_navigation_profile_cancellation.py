from pathlib import Path


ROOT = Path(__file__).parents[1]
NAVIGATION = ROOT / "frontend" / "navigation_error_overrides.js"


def _section(source: str, start: str, end: str) -> str:
    return source[source.index(start):source.index(end)]


def test_profile_scene_pagination_stops_when_navigation_is_stale():
    source = NAVIGATION.read_text(encoding="utf-8")
    compact = source.replace(" ", "")

    assert "loadAllPerformerScenes=asyncfunction(id,localId=null,generation=navigationGeneration)" in compact
    assert "loadAllStudioScenes=asyncfunction(id,localId=null,generation=navigationGeneration)" in compact
    assert "performerProfile=asyncfunction(id,localId=null)" in compact
    assert "studioProfile=asyncfunction(id,localId=null)" in compact

    performer_loader = _section(
        source,
        "loadAllPerformerScenes=async function",
        "loadAllStudioScenes=async function",
    )
    studio_loader = _section(
        source,
        "loadAllStudioScenes=async function",
        "performerProfile=async function",
    )
    performer_profile = _section(
        source,
        "performerProfile=async function",
        "studioProfile=async function",
    )
    studio_profile = source[source.index("studioProfile=async function"):]

    for loader in (performer_loader, studio_loader):
        assert "navigationGenerationCurrent(generation)" in loader
        assert loader.count("navigationGenerationCurrent(generation)") >= 2

    assert "initProfileSceneCatalog('performers',id,resolvedLocalId,generation)" in performer_profile.replace(" ", "")
    assert "initProfileSceneCatalog('studios',id,resolvedLocalId,generation)" in studio_profile.replace(" ", "")
    assert "load(id,localId,generation)" in compact


def test_remote_performer_profile_does_not_require_a_second_local_lookup():
    source = NAVIGATION.read_text(encoding="utf-8")
    profile = _section(
        source,
        "performerProfile=async function",
        "studioProfile=async function",
    )

    assert profile.count("/api/library/performers/by-tpdb/") == 1
    assert "await api(`/api/metadata/performers/${encodeURIComponent(id)}`)" in profile
    assert "Do not perform a second local-only lookup here" in profile


def test_remote_studio_profile_does_not_require_a_second_local_lookup():
    source = NAVIGATION.read_text(encoding="utf-8")
    profile = source[source.index("studioProfile=async function") :]

    assert profile.count("/api/library/studios/by-tpdb/") == 1
    assert "await api(`/api/metadata/studios/${encodeURIComponent(id)}`)" in profile
    assert "Do not perform a second local-only lookup after remote metadata loads" in profile
