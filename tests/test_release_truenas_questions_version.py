from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _release_module():
    path = ROOT / "tools" / "release_version.py"
    spec = importlib.util.spec_from_file_location("scarletx_release_version_questions", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_helper_versions_truenas_questions_service_names(tmp_path):
    module = _release_module()
    questions = "packaging/truenas/scarletx/questions.yaml"

    assert questions in module.VERSIONED_FILES

    current = "0.3.10-beta.4"
    expected = "0.3.10"
    for relative_path in module.VERSIONED_FILES:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative_path == "pyproject.toml":
            path.write_text(
                f'[project]\nname = "scarletx"\nversion = "{current}"\n',
                encoding="utf-8",
            )
        elif relative_path == questions:
            path.write_text(
                f"- value: scarletx-{current}-backend\n"
                f"- value: scarletx-{current}-web\n",
                encoding="utf-8",
            )
        else:
            path.write_text(f"release marker {current}\n", encoding="utf-8")

    assert module.apply_release(tmp_path, "Stable release notes.") == expected
    updated = (tmp_path / questions).read_text(encoding="utf-8")
    assert current not in updated
    assert f"scarletx-{expected}-backend" in updated
    assert f"scarletx-{expected}-web" in updated
