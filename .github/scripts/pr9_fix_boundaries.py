from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


for name in ("settings", "library", "downloads", "automation"):
    path = ROOT / "scarletx" / "routes" / f"{name}.py"
    text = path.read_text(encoding="utf-8")
    old = '''    selected_ids = {id(route) for route in selected}\n    app.router.routes = [route for route in app.router.routes if id(route) not in selected_ids]\n    router.routes.extend(selected)\n    app.include_router(router)\n'''
    new = '''    # Keep the application's registered route objects untouched. The focused\n    # router is an ownership/introspection view over those exact objects, so paths,\n    # methods, dependencies, names, middleware behavior, and OpenAPI stay identical.\n    router.routes.extend(selected)\n'''
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected one mutable route adoption block, found {text.count(old)}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

application_path = ROOT / "scarletx" / "routes" / "application.py"
application = application_path.read_text(encoding="utf-8")
old_application_tail = '''# Re-home the legacy route declarations behind focused APIRouter boundaries.\n# Route objects retain their handler functions, names, methods, dependencies,\n# response models, and paths; the characterization fixture protects the public API.\nfrom . import automation as _automation_routes\nfrom . import downloads as _download_routes\nfrom . import library as _library_routes\nfrom . import settings as _settings_routes\n\nfor _route_module in (\n    _settings_routes,\n    _library_routes,\n    _download_routes,\n    _automation_routes,\n):\n    _route_module.adopt_routes(app)\n'''
new_application_tail = '''# Group the legacy route declarations behind focused APIRouter ownership views.\n# Import locally so the relocated legacy implementation does not acquire new E402\n# exceptions; route objects stay registered on the original application router.\ndef _adopt_route_boundaries() -> None:\n    from . import automation as automation_routes\n    from . import downloads as download_routes\n    from . import library as library_routes\n    from . import settings as settings_routes\n\n    for route_module in (\n        settings_routes,\n        library_routes,\n        download_routes,\n        automation_routes,\n    ):\n        route_module.adopt_routes(app)\n\n\n_adopt_route_boundaries()\n'''
if application.count(old_application_tail) != 1:
    raise SystemExit("application route-boundary tail target not found exactly once")
application_path.write_text(
    application.replace(old_application_tail, new_application_tail, 1), encoding="utf-8"
)

boundary_exports = {
    "transport.py": ("SegmentFetcher", "UsenetProviderConfig", "test_provider", "native_client_ready"),
    "decode.py": ("decode_yenc_native", "decode_yenc_to_file", "decode_yenc_to_target", "DecodedSegment"),
    "postprocess.py": ("postprocess_payload", "unpack_payload", "recover_unknown_videos", "reprocess_completed_job"),
}
for filename, names in boundary_exports.items():
    path = ROOT / "scarletx" / "usenet" / filename
    assignments = "\n".join(f"{name} = _worker.{name}" for name in names)
    path.write_text(
        "from __future__ import annotations\n\n"
        "from . import worker as _worker\n\n"
        f"{assignments}\n\n"
        f"__all__ = {names!r}\n",
        encoding="utf-8",
    )

pyproject_path = ROOT / "pyproject.toml"
pyproject = pyproject_path.read_text(encoding="utf-8")
old_ruff = '''"scarletx/main.py" = ["E701", "E702", "F401"]\n"scarletx/media_library.py" = ["E701", "E702"]\n'''
new_ruff = '''"scarletx/main.py" = ["E701", "E702", "F401"]\n"scarletx/routes/application.py" = ["E701", "E702", "F401"]\n"scarletx/media_library.py" = ["E701", "E702"]\n'''
if pyproject.count(old_ruff) != 1:
    raise SystemExit("main Ruff relocation target not found exactly once")
pyproject = pyproject.replace(old_ruff, new_ruff, 1)
old_native_ruff = '''"scarletx/native_usenet.py" = ["F401"]\n"scarletx/rss.py" = ["E701", "E702"]\n'''
new_native_ruff = '''"scarletx/native_usenet.py" = ["F401"]\n"scarletx/usenet/worker.py" = ["F401"]\n"scarletx/rss.py" = ["E701", "E702"]\n'''
if pyproject.count(old_native_ruff) != 1:
    raise SystemExit("native Usenet Ruff relocation target not found exactly once")
pyproject_path.write_text(pyproject.replace(old_native_ruff, new_native_ruff, 1), encoding="utf-8")

module_tests = ROOT / "tests" / "test_module_boundaries.py"
text = module_tests.read_text(encoding="utf-8")
old = '''def test_frontend_dom_ids_are_stable():\n    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")\n    current = sorted(set(re.findall(r'\\bid=["\\']([^"\\']+)["\\']', html)))\n    assert current == json.loads(DOM_IDS.read_text())\n'''
new = '''def test_frontend_dom_ids_are_stable():\n    # The pre-extraction fixture intentionally captured IDs appearing in both\n    # static markup and JavaScript-generated templates. Preserve that same source\n    # universe after moving the application script into app.js.\n    source = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")\n    source += "\\n" + (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")\n    current = sorted(set(re.findall(r'\\bid=["\\']([^"\\']+)["\\']', source)))\n    assert current == json.loads(DOM_IDS.read_text())\n'''
if text.count(old) != 1:
    raise SystemExit("module boundary DOM test replacement target not found exactly once")
module_tests.write_text(text.replace(old, new, 1), encoding="utf-8")

theme_path = ROOT / "tests" / "test_ui_theme.py"
theme = theme_path.read_text(encoding="utf-8")
old_theme = '''INDEX = Path(__file__).parents[1] / "frontend" / "index.html"\n\n\ndef html() -> str:\n    return INDEX.read_text(encoding="utf-8")\n'''
new_theme = '''FRONTEND = Path(__file__).parents[1] / "frontend"\nINDEX = FRONTEND / "index.html"\nSTYLES = FRONTEND / "styles.css"\n\n\ndef html() -> str:\n    # Theme assertions remain byte-for-byte checks of the same CSS tokens/rules,\n    # but PR9 moves the stylesheet into its own static asset.\n    return INDEX.read_text(encoding="utf-8") + "\\n" + STYLES.read_text(encoding="utf-8")\n'''
if theme.count(old_theme) != 1:
    raise SystemExit("theme helper replacement target not found exactly once")
theme_path.write_text(theme.replace(old_theme, new_theme, 1), encoding="utf-8")
