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
