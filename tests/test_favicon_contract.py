from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_web_shell_uses_packaged_approved_svg_favicon():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")

    expected_href = "/scarletx-icon.svg?v=approved-20260916-1"
    expected_link = (
        f'<link rel="icon" href="{expected_href}" '
        'type="image/svg+xml" sizes="any">'
    )

    assert expected_link in index
    assert 'rel="icon" href="/scarletx-icon.webp' not in index
    assert (
        "COPY frontend/scarletx-icon.svg "
        "/usr/share/nginx/html/scarletx-icon.svg"
    ) in dockerfile
    assert f"grep -q '{expected_href}' /usr/share/nginx/html/index.html" in dockerfile
