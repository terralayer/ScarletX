from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "scarletx"
FRONTEND = ROOT / "frontend"


def deepen_relative_imports(text: str) -> str:
    return re.sub(r"(?m)^(\s*)from \.(?!\.)", r"\1from ..", text)


def write_route_module(path: Path, prefixes: tuple[str, ...], description: str) -> None:
    path.write_text(
        "from __future__ import annotations\n\n"
        "from fastapi import APIRouter\n"
        "from fastapi.routing import APIRoute\n\n"
        f'\"\"\"{description}\"\"\"\n\n'
        f"PREFIXES = {prefixes!r}\n"
        "router = APIRouter()\n\n\n"
        "def adopt_routes(app) -> None:\n"
        "    if router.routes:\n"
        "        return\n"
        "    selected = [\n"
        "        route for route in app.router.routes\n"
        "        if isinstance(route, APIRoute)\n"
        "        and any(route.path.startswith(prefix) for prefix in PREFIXES)\n"
        "    ]\n"
        "    if not selected:\n"
        "        return\n"
        "    selected_ids = {id(route) for route in selected}\n"
        "    app.router.routes = [route for route in app.router.routes if id(route) not in selected_ids]\n"
        "    router.routes.extend(selected)\n"
        "    app.include_router(router)\n",
        encoding="utf-8",
    )


def move_backend() -> None:
    routes = PKG / "routes"
    usenet = PKG / "usenet"
    routes.mkdir(exist_ok=True)
    usenet.mkdir(exist_ok=True)
    (routes / "__init__.py").write_text('"""ScarletX API composition boundaries."""\n', encoding="utf-8")
    (usenet / "__init__.py").write_text('"""ScarletX native Usenet subsystem boundaries."""\n', encoding="utf-8")

    main_path = PKG / "main.py"
    application_path = routes / "application.py"
    main_text = main_path.read_text(encoding="utf-8")
    if "__file__" in main_text:
        raise SystemExit("main.py uses __file__; path-sensitive relocation requires explicit handling")
    application_text = deepen_relative_imports(main_text)
    application_text += """

# Re-home the legacy route declarations behind focused APIRouter boundaries.
# Route objects retain their handler functions, names, methods, dependencies,
# response models, and paths; the characterization fixture protects the public API.
from . import automation as _automation_routes
from . import downloads as _download_routes
from . import library as _library_routes
from . import settings as _settings_routes

for _route_module in (
    _settings_routes,
    _library_routes,
    _download_routes,
    _automation_routes,
):
    _route_module.adopt_routes(app)
"""
    application_path.write_text(application_text, encoding="utf-8")
    main_path.write_text(
        "from __future__ import annotations\n\n"
        "# Compatibility facade: callers importing scarletx.main receive the relocated\n"
        "# application module itself, so monkeypatching and private compatibility imports\n"
        "# continue to operate on the implementation globals.\n"
        "import sys as _sys\n"
        "from .routes import application as _application\n\n"
        "_parent = _sys.modules.get(__package__)\n"
        "if _parent is not None:\n"
        "    setattr(_parent, 'main', _application)\n"
        "_sys.modules[__name__] = _application\n",
        encoding="utf-8",
    )

    write_route_module(
        routes / "settings.py",
        (
            "/api/settings", "/api/indexers", "/api/download-client", "/api/download-clients",
            "/api/quality-profiles", "/api/release-profiles", "/api/root-folders", "/api/backups",
            "/api/blocklist",
        ),
        "Settings, provider, profile, root-folder, backup, and blocklist routes.",
    )
    write_route_module(
        routes / "library.py",
        (
            "/api/library", "/api/media-files", "/api/media-library", "/api/manual-import",
            "/api/metadata", "/api/artwork",
        ),
        "Library, media-file, metadata, artwork, and manual-import routes.",
    )
    write_route_module(
        routes / "downloads.py",
        ("/api/activity", "/api/downloads", "/api/history", "/api/jobs"),
        "Download queue, activity, history, and job routes.",
    )
    write_route_module(
        routes / "automation.py",
        ("/api/automation", "/api/search", "/api/rss", "/api/wanted", "/api/calendar"),
        "Automation, search, RSS, wanted, and calendar routes.",
    )

    native_path = PKG / "native_usenet.py"
    worker_path = usenet / "worker.py"
    worker_text = native_path.read_text(encoding="utf-8")
    if "__file__" in worker_text:
        raise SystemExit("native_usenet.py uses __file__; path-sensitive relocation requires explicit handling")
    worker_path.write_text(deepen_relative_imports(worker_text), encoding="utf-8")
    native_path.write_text(
        "from __future__ import annotations\n\n"
        "# Compatibility alias: preserve the historical module object so tests, plugins,\n"
        "# and callers that monkeypatch scarletx.native_usenet still patch worker globals.\n"
        "import sys as _sys\n"
        "from .usenet import worker as _worker\n\n"
        "_parent = _sys.modules.get(__package__)\n"
        "if _parent is not None:\n"
        "    setattr(_parent, 'native_usenet', _worker)\n"
        "_sys.modules[__name__] = _worker\n",
        encoding="utf-8",
    )

    boundary_modules = {
        "transport.py": (
            "SegmentFetcher", "UsenetProviderConfig", "test_provider", "native_client_ready",
        ),
        "decode.py": (
            "decode_yenc_native", "decode_yenc_to_file", "decode_yenc_to_target", "DecodedSegment",
        ),
        "postprocess.py": (
            "postprocess_payload", "unpack_payload", "recover_unknown_videos", "reprocess_completed_job",
        ),
    }
    for filename, names in boundary_modules.items():
        (usenet / filename).write_text(
            "from __future__ import annotations\n\n"
            "from . import worker as _worker\n\n"
            f"__all__ = {names!r}\n\n\n"
            "def __getattr__(name: str):\n"
            "    if name in __all__:\n"
            "        return getattr(_worker, name)\n"
            "    raise AttributeError(name)\n",
            encoding="utf-8",
        )


def extract_frontend() -> None:
    index_path = FRONTEND / "index.html"
    html = index_path.read_text(encoding="utf-8")

    style_matches = list(re.finditer(r"<style>(.*?)</style>", html, flags=re.I | re.S))
    if len(style_matches) != 1:
        raise SystemExit(f"expected one inline style block, found {len(style_matches)}")
    style = style_matches[0]
    styles = style.group(1).strip() + "\n"
    html = html[: style.start()] + '<link rel="stylesheet" href="/styles.css">' + html[style.end() :]
    (FRONTEND / "styles.css").write_text(styles, encoding="utf-8")

    script_matches = list(
        re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, flags=re.I | re.S)
    )
    if len(script_matches) != 1:
        raise SystemExit(f"expected one inline application script, found {len(script_matches)}")
    script = script_matches[0]
    app_js = script.group(1).strip() + "\n"
    html = html[: script.start()] + '<script src="/app.js"></script>' + html[script.end() :]
    (FRONTEND / "app.js").write_text(app_js, encoding="utf-8")
    index_path.write_text(html, encoding="utf-8")

    docker_path = ROOT / "Dockerfile.web"
    docker = docker_path.read_text(encoding="utf-8")
    docker = docker.replace(
        "COPY frontend/auth.js /usr/share/nginx/html/auth.js\n",
        "COPY frontend/auth.js /usr/share/nginx/html/auth.js\n"
        "COPY frontend/styles.css /usr/share/nginx/html/styles.css\n"
        "COPY frontend/app.js /usr/share/nginx/html/app.js\n",
        1,
    )
    docker = docker.replace(
        "    sed -i 's/^[[:space:]]*boot();[[:space:]]*$/authGateBoot(boot);/' /usr/share/nginx/html/index.html; \\\n",
        "    sed -i 's/^[[:space:]]*boot();[[:space:]]*$/authGateBoot(boot);/' /usr/share/nginx/html/app.js; \\\n",
        1,
    )
    docker = docker.replace(
        "    grep -q '/auth.js' /usr/share/nginx/html/index.html; \\\n    grep -q 'authGateBoot(boot);' /usr/share/nginx/html/index.html\n",
        "    grep -q '/auth.js' /usr/share/nginx/html/index.html; \\\n"
        "    grep -q '/styles.css' /usr/share/nginx/html/index.html; \\\n"
        "    grep -q '/app.js' /usr/share/nginx/html/index.html; \\\n"
        "    grep -q 'authGateBoot(boot);' /usr/share/nginx/html/app.js\n",
        1,
    )
    docker_path.write_text(docker, encoding="utf-8")


def write_tests() -> None:
    path = ROOT / "tests" / "test_module_boundaries.py"
    path.write_text(
        r'''from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.routing import APIRoute

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "tests" / "fixtures" / "route_contract_0310.json"
DOM_IDS = ROOT / "tests" / "fixtures" / "dom_ids_0310.json"


def route_contract(app):
    rows = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = sorted(getattr(route, "methods", None) or [])
        if path and methods:
            rows.append({"path": path, "methods": methods})
    return sorted(rows, key=lambda item: (item["path"], item["methods"]))


def line_count(relative: str) -> int:
    return len((ROOT / relative).read_text(encoding="utf-8").splitlines())


def test_route_and_method_contract_is_stable():
    from scarletx.app import app

    assert route_contract(app) == json.loads(ROUTES.read_text())
    assert any(isinstance(route, APIRoute) for route in app.routes)


def test_focused_route_boundaries_adopt_real_routes():
    from scarletx.app import app  # noqa: F401
    from scarletx.routes import automation, downloads, library, settings

    for module in (settings, library, downloads, automation):
        assert module.router.routes, module.__name__
        assert all(isinstance(route, APIRoute) for route in module.router.routes)


def test_native_usenet_public_imports_remain_available_and_patchable(monkeypatch):
    from scarletx import native_usenet as native
    from scarletx.native_usenet import SegmentFetcher, process_job, queue_rows
    from scarletx.usenet import worker

    assert SegmentFetcher and process_job and queue_rows
    marker = object()
    monkeypatch.setattr(native, "NNTPConnection", marker)
    assert worker.NNTPConnection is marker


def test_usenet_subsystem_boundaries_expose_stable_interfaces():
    from scarletx.usenet import decode, postprocess, transport

    assert transport.SegmentFetcher
    assert transport.UsenetProviderConfig
    assert decode.decode_yenc_to_file
    assert decode.decode_yenc_to_target
    assert postprocess.postprocess_payload
    assert postprocess.unpack_payload


def test_frontend_dom_ids_are_stable():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    current = sorted(set(re.findall(r'\bid=["\']([^"\']+)["\']', html)))
    assert current == json.loads(DOM_IDS.read_text())


def test_frontend_assets_are_external_and_auth_boot_order_is_preserved():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    auth = (ROOT / "frontend" / "auth.js").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")

    assert "<style>" not in html
    assert '<link rel="stylesheet" href="/styles.css">' in html
    assert '<script src="/app.js"></script>' in html
    assert "boot();" in app_js
    assert "window.authGateBoot" in auth
    assert "COPY frontend/styles.css" in dockerfile
    assert "COPY frontend/app.js" in dockerfile
    assert "authGateBoot(boot)" in dockerfile


def test_composition_modules_are_not_monoliths():
    assert line_count("scarletx/main.py") < 800
    assert line_count("scarletx/native_usenet.py") < 400
    assert line_count("frontend/index.html") < 1_200
''',
        encoding="utf-8",
    )


move_backend()
extract_frontend()
write_tests()
