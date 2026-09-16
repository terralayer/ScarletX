from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scarletx.db import Base, get_session
from scarletx.models import History


ROOT = Path(__file__).resolve().parents[1]


def _client(tmp_path: Path):
    from scarletx.activity_history import router

    engine = create_engine(
        f"sqlite:///{tmp_path / 'activity-history.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    base = datetime(2026, 9, 16, tzinfo=UTC)

    with factory() as db:
        for index in range(90):
            db.add(
                History(
                    event_type="download",
                    message=f"Download event {index}",
                    created_at=base + timedelta(minutes=index),
                )
            )
        for index in range(35):
            db.add(
                History(
                    event_type="import",
                    message=f"Import event {index}",
                    created_at=base + timedelta(minutes=90 + index),
                )
            )
        db.commit()

    app = FastAPI()
    app.include_router(router)

    def override_session():
        with factory() as db:
            yield db

    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def test_activity_history_page_is_bounded_and_reports_total_and_event_counts(tmp_path):
    client = _client(tmp_path)

    response = client.get("/api/history/page?page=2&limit=50")

    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 2
    assert payload["limit"] == 50
    assert payload["total"] == 125
    assert len(payload["items"]) == 50
    assert payload["event_counts"] == {"download": 90, "import": 35}
    assert payload["items"][0]["message"] == "Download event 74"
    assert payload["items"][-1]["message"] == "Download event 25"


def test_activity_history_event_filter_applies_to_rows_and_total_without_hiding_filter_counts(tmp_path):
    client = _client(tmp_path)

    response = client.get("/api/history/page?page=1&limit=20&event_type=import")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 35
    assert len(payload["items"]) == 20
    assert {item["event_type"] for item in payload["items"]} == {"import"}
    assert payload["event_counts"] == {"download": 90, "import": 35}


def test_activity_history_limit_is_capped_at_one_hundred(tmp_path):
    client = _client(tmp_path)

    response = client.get("/api/history/page?page=1&limit=101")

    assert response.status_code == 422


def test_composed_application_registers_paged_and_legacy_history_routes_once():
    from scarletx.app import app

    paged = [
        route
        for route in app.router.routes
        if getattr(route, "path", None) == "/api/history/page"
        and "GET" in (getattr(route, "methods", set()) or set())
    ]
    legacy = [
        route
        for route in app.router.routes
        if getattr(route, "path", None) == "/api/history"
        and "GET" in (getattr(route, "methods", set()) or set())
    ]
    assert len(paged) == 1
    assert len(legacy) == 1


def test_activity_history_ui_override_is_bounded_filtered_and_packaged():
    source = (ROOT / "frontend" / "activity_history_overrides.js").read_text(encoding="utf-8")
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")

    assert "ACTIVITY_HISTORY_PAGE_SIZE=50" in source
    assert "activityHistoryPage=1" in source
    assert "activityHistoryEventType=''" in source
    assert "/api/history/page?page=${activityHistoryPage}&limit=${ACTIVITY_HISTORY_PAGE_SIZE}" in source
    assert "activityPager('history'" in source
    assert "activityHistoryFilter" in source
    assert "event_counts" in source
    assert "'/api/history?limit=200'" in source
    assert "/activity_history_overrides.js" in index
    assert "COPY frontend/activity_history_overrides.js /usr/share/nginx/html/activity_history_overrides.js" in dockerfile
    assert "grep -q '/activity_history_overrides.js'" in dockerfile
