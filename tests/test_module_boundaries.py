from __future__ import annotations

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
    from scarletx.app import app
    from scarletx.routes import automation, downloads, library, settings

    registered = {id(route) for route in app.routes if isinstance(route, APIRoute)}
    for module in (settings, library, downloads, automation):
        assert module.router.routes, module.__name__
        assert all(isinstance(route, APIRoute) for route in module.router.routes)
        assert {id(route) for route in module.router.routes} <= registered


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
    # The pre-extraction fixture intentionally captured IDs appearing in both
    # static markup and JavaScript-generated templates. Preserve that same source
    # universe after moving the application script into app.js.
    source = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    source += "\n" + (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    current = sorted(set(re.findall(r'\bid=["\']([^"\']+)["\']', source)))
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


def test_temporary_pr9_repair_workflows_are_not_committed():
    workflow_dir = ROOT / ".github" / "workflows"
    assert not (workflow_dir / "pr9-apply.yml").exists()
    assert not (workflow_dir / "pr9-fix-ci-contracts.yml").exists()
