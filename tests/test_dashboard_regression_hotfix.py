from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_hotfix_is_loaded_last():
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert '<script src="/dashboard_regression_hotfix.js"></script>' in index


def test_dashboard_cards_are_force_bound_to_respective_pages():
    source = (ROOT / "frontend" / "dashboard_regression_hotfix.js").read_text(encoding="utf-8")
    assert "#stats .dashboard-stat" in source
    assert "Scenes: 'scenes'" in source
    assert "Performers: 'performers'" in source
    assert "Studios: 'studios'" in source
    assert "Wanted: 'wanted'" in source
    assert "Storage: 'library'" in source


def test_dashboard_scene_table_restores_performers_column():
    source = (ROOT / "frontend" / "dashboard_regression_hotfix.js").read_text(encoding="utf-8")
    assert "<th>Performers</th>" in source
    assert "sceneRowsHtml(rows,inLibrary)" in source


def test_small_studio_icons_use_transparent_compact_artwork():
    source = (ROOT / "frontend" / "dashboard_regression_hotfix.js").read_text(encoding="utf-8")
    assert "/compact?v=v6" in source
    backend = (ROOT / "scarletx" / "compact_studio_art.py").read_text(encoding="utf-8")
    assert "prepare_compact_studio_artwork" in backend
    assert "Image.new(\"RGBA\", target_size, (0, 0, 0, 0))" in backend
    app = (ROOT / "scarletx" / "app.py").read_text(encoding="utf-8")
    assert "install_compact_studio_art_route(app)" in app
