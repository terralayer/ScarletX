from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_web_shell_uses_packaged_approved_webp_favicon():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")

    expected_href = "/scarletx-icon.webp?v=approved-20260918-1"
    expected_link = (
        f'<link rel="icon" href="{expected_href}" '
        'type="image/webp" sizes="any">'
    )

    assert expected_link in index
    assert 'rel="icon" href="/scarletx-icon.svg' not in index
    assert (
        "COPY frontend/scarletx-icon.webp "
        "/usr/share/nginx/html/scarletx-icon.webp"
    ) in dockerfile
    assert f"grep -q '{expected_href}' /usr/share/nginx/html/index.html" in dockerfile


def test_web_shell_prioritizes_a_broadly_supported_png_favicon_fallback():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")

    expected_href = "/scarletx-icon.png?v=approved-20260918-1"
    expected_link = (
        f'<link rel="icon" href="{expected_href}" '
        'type="image/png" sizes="128x128">'
    )

    assert expected_link in index
    assert index.index(expected_link) < index.index('/scarletx-icon.webp?v=approved-20260918-1')
    assert (FRONTEND / "scarletx-icon.png").exists()
    assert (
        "COPY frontend/scarletx-icon.png "
        "/usr/share/nginx/html/scarletx-icon.png"
    ) in dockerfile
