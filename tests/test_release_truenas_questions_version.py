from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_catalog_service_names_stay_stable_across_upstream_releases():
    values = yaml.safe_load((ROOT / "packaging/truenas/scarletx/ix_values.yaml").read_text())
    assert values["consts"]["scarletx_backend_container_name"] == "backend"
    assert values["consts"]["scarletx_web_container_name"] == "web"
    assert values["consts"]["perms_container_name"] == "permissions"
    questions = (ROOT / "packaging/truenas/scarletx/questions.yaml").read_text()
    assert "scarletx-0." not in questions
