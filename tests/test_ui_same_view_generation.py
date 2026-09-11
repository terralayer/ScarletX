from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_navigation_override_uses_generation_tokens_for_same_view_requests():
    source = (ROOT / "frontend" / "navigation_error_overrides.js").read_text(encoding="utf-8")
    compact = "".join(source.split())

    assert "letnavigationGeneration=" in compact
    assert "functionnextNavigationGeneration(" in compact
    assert "functionnavigationGenerationCurrent(" in compact
    assert "constgeneration=nextNavigationGeneration()" in compact
    assert "navigationGenerationCurrent(generation)" in compact


def test_entity_library_and_search_reject_stale_same_view_success_and_errors():
    source = (ROOT / "frontend" / "navigation_error_overrides.js").read_text(encoding="utf-8")
    compact = "".join(source.split())

    assert "loadEntityLibrary=asyncfunction" in compact
    assert "searchEntity=asyncfunction" in compact
    assert compact.count("!navigationGenerationCurrent(generation)") >= 4
