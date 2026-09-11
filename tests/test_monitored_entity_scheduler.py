from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_monitored_entity_discovery_runs_hourly_from_application_lifespan():
    source = (ROOT / "scarletx" / "routes" / "application.py").read_text(encoding="utf-8")

    assert "monitored_entity_discovery_cycle" in source
    assert "MONITORED_ENTITY_DISCOVERY_INTERVAL_SECONDS = 3600" in source
    assert "await monitored_entity_discovery_cycle(SessionLocal, settings)" in source


def test_automatic_search_skips_future_release_dates():
    source = (ROOT / "scarletx" / "automation.py").read_text(encoding="utf-8")

    assert "date.today()" in source
    assert "scene.release_date and scene.release_date > date.today()" in source
