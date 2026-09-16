from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_hotfix_is_loaded_last():
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert '<script src="/dashboard_regression_hotfix.js"></script>' in index


def test_dashboard_cards_prefer_native_explicit_navigation_targets():
    source = (ROOT / "frontend" / "dashboard_regression_hotfix.js").read_text(encoding="utf-8")
    assert "#stats .dashboard-stat" in source
    assert "return card.dataset.statGo || dashboardTargets[label] || null" in source
    assert "Performers: 'performers'" in source
    assert "Studios: 'studios'" in source
    assert "Wanted: 'wanted'" in source
    assert "Storage: 'library'" in source

    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "dashboardStat(dashboardIcons.scenes" in app
    assert "'Inyourlibrary','library'" in app.replace(" ", "")


def test_approved_sidebar_shortcuts_are_wired_without_legacy_layout_script():
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    source = (ROOT / "frontend" / "dashboard_regression_hotfix.js").read_text(encoding="utf-8")

    assert '<script src="/locked_dashboard_layout.js"></script>' not in index
    assert 'data-approved-nav="discover"' in index
    assert 'data-approved-nav="indexers"' in index
    assert "function wireApprovedSidebarShortcuts()" in source
    assert "entityMode.scenes = 'search'" in source
    assert "renderEntities('scenes')" in source
    assert "settingsTab = 'indexers'" in source
    assert "setApprovedNavActive('discover')" in source
    assert "setApprovedNavActive('indexers')" in source


def test_dashboard_scene_table_restores_performers_column():
    source = (ROOT / "frontend" / "dashboard_regression_hotfix.js").read_text(encoding="utf-8")
    assert "<th>Performers</th>" in source
    assert "sceneRowsHtml(rows,inLibrary)" in source


def test_small_studio_icons_use_transparent_compact_artwork():
    source = (ROOT / "frontend" / "dashboard_regression_hotfix.js").read_text(encoding="utf-8")
    assert "/compact?v=v6" in source
    backend = (ROOT / "scarletx" / "compact_studio_art.py").read_text(encoding="utf-8")
    assert "prepare_compact_studio_artwork" in backend
    assert 'Image.new("RGBA", target_size, (0, 0, 0, 0))' in backend
    composition = (ROOT / "scarletx" / "runtime_composition.py").read_text(encoding="utf-8")
    assert "install_compact_studio_art_route(app)" in composition
