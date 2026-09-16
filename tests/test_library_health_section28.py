from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scarletx.db import Base, get_session
from scarletx.models import MediaFile, MediaProbe, Scene, UnmatchedMediaFile


def _client(tmp_path: Path):
    from scarletx.library_health import router

    engine = create_engine(f"sqlite:///{tmp_path / 'library-health.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as db:
        scene = Scene(tpdb_id="scene-health-1", title="Health Scene")
        db.add(scene)
        db.flush()

        missing = MediaFile(scene_id=scene.id, path="/media/missing.mp4", size_bytes=100)
        healthy = MediaFile(scene_id=scene.id, path="/media/healthy.mp4", size_bytes=200)
        unprobed = MediaFile(scene_id=scene.id, path="/media/unprobed.mp4", size_bytes=300)
        db.add_all([missing, healthy, unprobed])
        db.flush()

        db.add_all(
            [
                MediaProbe(media_file_id=missing.id, missing=True, size_bytes=100),
                MediaProbe(media_file_id=healthy.id, missing=False, size_bytes=200),
                UnmatchedMediaFile(path="/media/unmatched.mp4", display_name="Unmatched Scene", size_bytes=400, missing=False),
                UnmatchedMediaFile(path="/media/gone.mp4", display_name="Gone Scene", size_bytes=500, missing=True),
            ]
        )
        db.commit()

    app = FastAPI()
    app.include_router(router)

    def override_session():
        with factory() as db:
            yield db

    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def test_library_health_counts_local_actionable_issues_without_exposing_paths(tmp_path):
    client = _client(tmp_path)

    response = client.get("/api/media-library/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["counts"] == {"missing": 1, "unmatched": 1, "unprobed": 1, "total": 3}
    assert len(payload["issues"]) == 3
    assert {item["kind"] for item in payload["issues"]} == {"missing", "unmatched", "unprobed"}
    assert all("path" not in item for item in payload["issues"])


def test_library_health_limits_issue_rows_to_fifty(tmp_path):
    client = _client(tmp_path)

    from scarletx.db import get_session as dependency

    override = client.app.dependency_overrides[dependency]
    with next(override()) as db:
        for index in range(60):
            db.add(
                UnmatchedMediaFile(
                    path=f"/media/extra-{index}.mp4",
                    display_name=f"Extra {index}",
                    size_bytes=index + 1,
                    missing=False,
                )
            )
        db.commit()

    payload = client.get("/api/media-library/health").json()
    assert payload["counts"]["unmatched"] == 61
    assert len(payload["issues"]) == 50


def test_composed_application_registers_library_health_route():
    from scarletx.app import app

    matches = [
        route
        for route in app.router.routes
        if getattr(route, "path", None) == "/api/media-library/health"
        and "GET" in (getattr(route, "methods", set()) or set())
    ]
    assert len(matches) == 1


def test_library_health_ui_override_is_isolated_and_packaged():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "frontend" / "library_health_overrides.js").read_text(encoding="utf-8")
    index = (root / "frontend" / "index.html").read_text(encoding="utf-8")
    dockerfile = (root / "Dockerfile.web").read_text(encoding="utf-8")

    assert "/api/media-library/health" in ui
    assert "Library Health" in ui
    assert "library-health" in ui
    assert "/library_health_overrides.js" in index
    assert "COPY frontend/library_health_overrides.js /usr/share/nginx/html/library_health_overrides.js" in dockerfile
    assert "grep -q '/library_health_overrides.js'" in dockerfile
