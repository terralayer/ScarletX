from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_header_uses_compact_balanced_desktop_proportions():
    styles = (ROOT / "frontend" / "locked_dashboard.css").read_text(encoding="utf-8")

    assert "height:82px" in styles
    assert "grid-template-columns:260px minmax(280px,500px) 1fr auto auto auto" in styles
    assert ".header-brand img{display:block;width:240px" in styles
    assert "font-size:14px" in styles


def test_header_action_controls_share_a_consistent_visual_height():
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert ".sfw-toggle{height:40px" in styles
    assert ".queue-pill{width:auto;min-width:112px;height:40px" in styles
