import base64
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
BANNER_SHA256 = "236fc1fdadd8c34fa5909dcf7d5dae6e346b410e04bf89c0409fc341fee02cad"
EXPECTED_CHUNK_BLOBS = {
    1: "c0a9c496504b1761110a3b62b6e3ed46d6a0b6e5",
    2: "9b15ff7f2f5b1a4ec8558340aa04fd36277dd2df",
    3: "7afcd8c8b1943ecc3892624eb6880e068e6d4b46",
    4: "04fbf4d1a2e8ba5d0ef258a0406eeee160f98fcd",
}


def _git_blob_sha(data: bytes) -> str:
    return __import__("hashlib").sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def test_approved_dashboard_is_native_in_core_runtime():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    css = (FRONTEND / "locked_dashboard.css").read_text(encoding="utf-8")
    footer_css = (FRONTEND / "locked_dashboard_footer.css").read_text(encoding="utf-8")
    approved_assets_css = (FRONTEND / "approved_assets.css").read_text(encoding="utf-8")

    assert 'data-layout="approved-dashboard-v1"' in index
    assert 'data-dashboard-render="native-v2"' in index
    assert '/scarletx-logo.webp' in index
    assert '/scarletx-icon.webp' in index
    assert '<span>Dashboard</span>' in index
    assert '<span>Performers</span>' in index
    assert '<span>Scenes</span>' in index
    assert '<span>Studios</span>' in index
    assert '<span>Calendar</span>' in index
    assert '<span>Discover</span>' in index
    assert '<span>Downloads</span>' in index
    assert '<span>Indexers</span>' in index
    assert '<span>Settings</span>' in index
    assert '<script src="/dashboard_v2.js"></script>' not in index
    assert '<script src="/locked_dashboard_layout.js"></script>' not in index
    assert '<link rel="stylesheet" href="/approved_assets.css">' in index
    assert 'Discover More. Manage Smarter.' in index

    dashboard_start = app.index("async function dashboard()")
    dashboard_end = app.index("function performerLinks", dashboard_start)
    dashboard = app[dashboard_start:dashboard_end]
    assert 'class="dashboard-hero"' in dashboard
    assert 'Discover. Monitor. Organize. Enjoy.' in dashboard
    assert 'class="stats approved-stat-grid"' in dashboard
    assert 'class="approved-dashboard-grid"' in dashboard
    assert 'id="recentScenes"' in dashboard
    assert 'id="calendarRows"' in dashboard
    assert 'MutationObserver' not in dashboard

    assert '.dashboard-hero' in css
    assert '.app-footer' in footer_css
    assert "url('/scarletx-banner.webp')" in approved_assets_css
    assert 'aspect-ratio:1321 / 163' in approved_assets_css
    assert '.dashboard-hero::after{display:none!important}' in approved_assets_css


def test_approved_banner_source_reconstructs_to_locked_bytes():
    chunks = []
    for part, expected_blob in EXPECTED_CHUNK_BLOBS.items():
        data = (FRONTEND / f"scarletx-banner.b64.{part}").read_bytes()
        assert _git_blob_sha(data) == expected_blob
        chunks.append(data.decode("ascii"))
    banner = base64.b64decode("".join(chunks), validate=True)
    assert sha256(banner).hexdigest() == BANNER_SHA256
    assert banner.startswith(b"RIFF")
    assert b"WEBP" in banner[:16]


def test_frontend_image_build_has_no_dashboard_override_or_mutation_script():
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    for asset in (
        "scarletx-logo.webp",
        "scarletx-icon.webp",
        "locked_dashboard.css",
        "locked_dashboard_footer.css",
        "approved_assets.css",
    ):
        assert f"COPY frontend/{asset} /usr/share/nginx/html/{asset}" in dockerfile
    for part in range(1, 5):
        assert f"COPY frontend/scarletx-banner.b64.{part} /tmp/scarletx-banner.b64.{part}" in dockerfile
    assert BANNER_SHA256 in dockerfile
    assert "base64 -d > /usr/share/nginx/html/scarletx-banner.webp" in dockerfile
    assert "COPY frontend/scarletx-hero.svg" not in dockerfile
    assert "COPY frontend/dashboard_v2.js" not in dockerfile
    assert "COPY frontend/locked_dashboard_layout.js" not in dockerfile
