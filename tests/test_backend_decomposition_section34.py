from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _line_count(path: str) -> int:
    return len((ROOT / path).read_text(encoding="utf-8").splitlines())


def test_runtime_composition_has_a_focused_install_boundary():
    from scarletx.runtime_composition import install_runtime_composition

    assert callable(install_runtime_composition)


def test_composed_app_is_a_small_entrypoint():
    source = (ROOT / "scarletx" / "app.py").read_text(encoding="utf-8")

    assert "install_runtime_composition" in source
    assert "def _add_dashboard_routes" not in source
    assert "def _patch_route_call" not in source
    assert _line_count("scarletx/app.py") < 80
    assert _line_count("scarletx/runtime_composition.py") < 180


def test_runtime_route_contract_remains_registered_after_decomposition():
    from scarletx.app import app

    paths = {getattr(route, "path", None) for route in app.routes}
    for path in (
        "/api/dashboard/scenes",
        "/api/dashboard/studios",
        "/api/dashboard/performers",
        "/api/wanted/bulk",
        "/api/history/page",
        "/api/media-library/health",
        "/api/system/metrics",
    ):
        assert path in paths
