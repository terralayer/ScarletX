from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_about_is_available_from_navigation_and_rendered_as_a_native_view():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")

    assert 'data-view="about"' in index
    assert "<span>About</span>" in index
    assert "if(view==='about')return about()" in app
    assert "function about()" in app
    assert "About ScarletX" in app
    assert "Discover. Monitor. Organize. Enjoy." in app
    assert 'id="aboutVersion"' in app
    assert 'id="aboutUpstream"' in app
    assert 'id="aboutAgreementStatus"' in app
    assert 'id="aboutAgreementDate"' in app
    assert 'id="aboutAgreementVersion"' in app
    assert 'class="about-mark"><img src="/scarletx-icon.webp' in app


def test_about_describes_local_first_behavior_without_exposing_configuration_details():
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    css = (FRONTEND / "ui_overrides.css").read_text(encoding="utf-8")

    about_start = app.index("function about()")
    about_end = app.index("function performerLinks", about_start)
    about = app[about_start:about_end]

    assert "local-first" in about.lower()
    assert "your library stays on your system" in about.lower()
    assert "/api/system/status" in about
    assert "/api/setup/agreement" in about
    assert "Project license" in about
    assert "ScarletX source" in about
    assert 'class="about-mark">X</div>' not in about
    about_mark = css[css.index(".about-mark{"):css.index(".about-mark img{")]
    assert "#b9c5d4" in about_mark
    assert "var(--scarlet)" not in about_mark
