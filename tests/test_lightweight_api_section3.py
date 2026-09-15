from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _client_with_library_data():
    from scarletx.app import app
    from scarletx.db import Base, get_session
    from scarletx.models import Performer, Scene, Studio

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        studio = Studio(tpdb_id="studio-light", name="Light Studio", is_library=True)
        performer = Performer(tpdb_id="performer-light", name="Light Performer", is_library=True)
        scene = Scene(
            tpdb_id="scene-light",
            title="Light Scene",
            content_type="scene",
            description="heavy detail must stay off list payloads",
            studio=studio,
        )
        scene.performers.append(performer)
        db.add(scene)
        db.commit()

    def override_session():
        with factory() as db:
            yield db

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), app


def test_library_page_routes_return_summary_payloads_only():
    client, app = _client_with_library_data()
    try:
        scenes = client.get("/api/library/scenes/page?limit=10").json()["items"]
        performers = client.get("/api/library/performers/page?limit=10").json()["items"]
        studios = client.get("/api/library/studios/page?limit=10").json()["items"]

        assert set(scenes[0]) == {
            "id", "tpdb_id", "title", "release_date", "image_url", "monitored",
            "studio", "studio_id", "performers", "has_file", "media_id",
        }
        assert set(performers[0]) == {
            "id", "tpdb_id", "name", "image_url", "aliases", "monitored",
        }
        assert set(studios[0]) == {
            "id", "tpdb_id", "name", "image_url", "monitored",
            "downloaded_scene_count", "scene_count",
        }
        assert "description" not in scenes[0]
        assert "bio" not in performers[0]
        assert "description" not in studios[0]
    finally:
        app.dependency_overrides.clear()


def test_library_page_routes_reject_unbounded_page_sizes():
    client, app = _client_with_library_data()
    try:
        assert client.get("/api/library/scenes/page?limit=251").status_code == 422
        assert client.get("/api/library/performers/page?limit=201").status_code == 422
        assert client.get("/api/library/studios/page?limit=201").status_code == 422
    finally:
        app.dependency_overrides.clear()
