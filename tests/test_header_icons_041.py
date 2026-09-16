from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def test_top_right_user_status_is_removed_and_downloads_uses_svg_icon():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")

    assert 'class="status-pill"' not in index
    assert 'data-icon="top-downloads"' in index
    assert '<span class="queue-glyph">♧</span>' not in index
