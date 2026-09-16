from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_shared_frontend_runtime_is_extracted_and_loaded_before_app():
    runtime_path = ROOT / "frontend" / "runtime_core.js"
    assert runtime_path.exists(), "Section 35 must extract shared frontend runtime helpers"

    runtime = runtime_path.read_text(encoding="utf-8")
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")

    for symbol in (
        "const $=",
        "const $$=",
        "const esc=",
        "const fmtDate=",
        "const bytes=",
        "const durationText=",
        "const api=",
        "const patch=",
        "function notify(",
        "function pageHead(",
        "function empty(",
        "function modal(",
    ):
        assert symbol in runtime
        assert symbol not in app

    runtime_tag = '<script src="/runtime_core.js"></script>'
    app_tag = '<script src="/app.js"></script>'
    assert runtime_tag in index
    assert index.index(runtime_tag) < index.index(app_tag)
    assert "COPY frontend/runtime_core.js /usr/share/nginx/html/runtime_core.js" in dockerfile
