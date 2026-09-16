from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def test_top_right_user_status_is_hidden_and_downloads_uses_svg_icon():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assets = (FRONTEND / "approved_assets.css").read_text(encoding="utf-8")
    compact_assets = "".join(assets.split())

    assert '.status-pill{display:none!important;}' in compact_assets
    assert 'data-icon="top-downloads"' in index
    assert '<span class="queue-glyph">♧</span>' not in index
