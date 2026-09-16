from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_truenas_catalog_uses_exact_approved_scarletx_icon():
    app_yaml = (ROOT / "packaging" / "truenas" / "scarletx" / "app.yaml").read_text(encoding="utf-8")
    truenas_icon = (ROOT / "docs" / "images" / "scarletx-icon.svg").read_bytes()
    approved_icon = (ROOT / "frontend" / "scarletx-icon.svg").read_bytes()

    assert "icon: https://raw.githubusercontent.com/terralayer/ScarletX/main/docs/images/scarletx-icon.svg" in app_yaml
    assert truenas_icon == approved_icon


def test_truenas_catalog_package_bumps_for_branding_asset_change():
    app_yaml = (ROOT / "packaging" / "truenas" / "scarletx" / "app.yaml").read_text(encoding="utf-8")

    assert "app_version: 0.4.7" in app_yaml
    assert "\nversion: 1.0.14\n" in app_yaml
