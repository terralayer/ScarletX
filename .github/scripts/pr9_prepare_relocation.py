from pathlib import Path

path = Path("scarletx/main.py")
text = path.read_text(encoding="utf-8")
old = 'WEB = Path(__file__).parent / "web" / "index.html"'
new = 'WEB = Path(__spec__.origin).parent.parent / "web" / "index.html"'
if text.count(old) != 1:
    raise SystemExit(f"expected one legacy WEB path, found {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
