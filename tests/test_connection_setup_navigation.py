from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_connection_setup_configure_buttons_focus_the_relevant_settings_form():
    source = (ROOT / "frontend" / "management_ui.js").read_text(encoding="utf-8")

    assert "const connectionTargets" in source
    assert "metadata:'#tpdbKey'" in source
    assert "indexers:'#indexers'" in source
    assert "downloads:'#nativeEnabled'" in source
    assert "await settings();" in source
    assert "scrollIntoView" in source
