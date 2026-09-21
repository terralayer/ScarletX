from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sfw_toggle_is_available_in_the_topbar_and_persists_its_preference():
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'id="sfwToggle"' in index
    assert "const SFW_MODE_STORAGE_KEY='scarletx-sfw-mode';" in app
    assert "document.body.classList.toggle('sfw-mode',enabled);" in app
    assert "localStorage.setItem(SFW_MODE_STORAGE_KEY,enabled?'1':'0');" in app


def test_sfw_mode_blurs_media_artwork_and_playback_without_blurring_navigation():
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "body.sfw-mode .media-poster img" in styles
    assert "body.sfw-mode .scene-thumb img" in styles
    assert "body.sfw-mode .performer-full-image img" in styles
    assert "body.sfw-mode .player-shell video" in styles
    assert ".topbar img" not in styles[styles.index("body.sfw-mode"):]


def test_sfw_mode_blurs_scene_names_in_libraries_and_dashboard():
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "body.sfw-mode .scene-title" in styles
    assert "body.sfw-mode .approved-recent-title" in styles
    assert "body.sfw-mode .scene-card h3" in styles
    assert "body.sfw-mode .pagehead h1" in styles
    assert "body.sfw-mode #calendarBody td:nth-child(2)" in styles
    assert "body.sfw-mode #modalTitle" in styles
    assert "body.sfw-mode .studio-link" in styles
    assert "body.sfw-mode .person-link" in styles
    assert "body.sfw-mode .approved-upcoming .row b" in styles
    assert "body.sfw-mode .live-title" in styles
    assert "body.sfw-mode #activityCompleted tbody td:first-child" in styles
