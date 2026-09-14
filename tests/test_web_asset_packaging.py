from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_every_index_script_is_copied_into_web_image():
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")

    script_paths = re.findall(r'<script\s+src="/([^"?]+\.js)', index)
    assert script_paths, "index.html should reference packaged JavaScript assets"

    missing = [
        path
        for path in script_paths
        if f"COPY frontend/{path} /usr/share/nginx/html/{path}" not in dockerfile
    ]

    assert missing == [], f"Dockerfile.web does not package referenced scripts: {missing}"
