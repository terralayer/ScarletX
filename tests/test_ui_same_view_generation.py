from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_navigation_override_uses_separate_generation_domains():
    source = (ROOT / "frontend" / "navigation_error_overrides.js").read_text(encoding="utf-8")
    compact = "".join(source.split())

    assert "letnavigationGeneration=" in compact
    assert "functionnextNavigationGeneration(" in compact
    assert "functionnavigationGenerationCurrent(" in compact
    assert "constentityRequestGeneration=" in compact
    assert "functionnextEntityRequest(type)" in compact
    assert "functionentityRequestCurrent(type,generation)" in compact


def test_entity_library_and_search_reject_stale_same_view_success_and_errors():
    navigation = (ROOT / "frontend" / "navigation_error_overrides.js").read_text(encoding="utf-8")
    search = (ROOT / "frontend" / "entity_search.js").read_text(encoding="utf-8")
    compact_navigation = "".join(navigation.split())
    compact_search = "".join(search.split())

    assert "loadEntityLibrary=asyncfunction" in compact_navigation
    assert compact_navigation.count("!entityRequestCurrent(type,generation)") >= 2
    assert "functionsearchEntity(type,query,options={})" in compact_search
    assert "constcurrent=()=>view===type&&entityRequestCurrent(type,generation)&&$('#entityGrid')===grid" in compact_search
    assert compact_search.count("if(!current())returnfalse") >= 2
