from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.routing import APIRoute

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / 'tests' / 'fixtures' / 'route_contract_0310.json'
DOM_IDS = ROOT / 'tests' / 'fixtures' / 'dom_ids_0310.json'


def route_contract(app):
    rows = []
    for route in app.routes:
        path = getattr(route, 'path', None)
        methods = sorted(getattr(route, 'methods', None) or [])
        if path and methods:
            rows.append({'path': path, 'methods': methods})
    return sorted(rows, key=lambda item: (item['path'], item['methods']))


def test_route_and_method_contract_is_stable():
    from scarletx.app import app

    assert route_contract(app) == json.loads(ROUTES.read_text())
    assert any(isinstance(route, APIRoute) for route in app.routes)


def test_native_usenet_public_imports_remain_available():
    from scarletx.native_usenet import SegmentFetcher, process_job, queue_rows

    assert SegmentFetcher and process_job and queue_rows


def test_frontend_dom_ids_are_stable():
    html = (ROOT / 'frontend' / 'index.html').read_text(encoding='utf-8')
    current = sorted(set(re.findall(r'\bid=["\']([^"\']+)["\']', html)))
    assert current == json.loads(DOM_IDS.read_text())


def test_authentication_boot_and_static_assets_remain_supported():
    html = (ROOT / 'frontend' / 'index.html').read_text(encoding='utf-8')
    auth = (ROOT / 'frontend' / 'auth.js').read_text(encoding='utf-8')
    dockerfile = (ROOT / 'Dockerfile.web').read_text(encoding='utf-8')

    assert 'boot();' in html or 'authGateBoot(boot);' in html
    assert 'window.authGateBoot' in auth
    assert 'COPY frontend/index.html' in dockerfile
    assert 'COPY frontend/auth.css' in dockerfile
    assert 'COPY frontend/auth.js' in dockerfile
