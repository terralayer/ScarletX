from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.db import Base
from scarletx.list_queries import performer_summary_page, studio_summary_page
from scarletx.models import MediaFile, Performer, Scene, Studio


def _factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_studio_summary_avoids_correlated_count_subqueries():
    engine, factory = _factory()
    with factory() as db:
        studios = [Studio(tpdb_id=f"s-{i}", name=f"Studio {i:03d}", is_library=True) for i in range(40)]
        db.add_all(studios)
        db.flush()
        for index, studio in enumerate(studios):
            for scene_index in range(4):
                scene = Scene(
                    tpdb_id=f"scene-{index}-{scene_index}",
                    title=f"Scene {index}-{scene_index}",
                    content_type="scene",
                    studio_id=studio.id,
                )
                db.add(scene)
                db.flush()
                if scene_index < 2:
                    db.add(MediaFile(scene_id=scene.id, path=f"/library/{scene.id}.mp4", size_bytes=1))
        db.commit()

        statements: list[str] = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(engine, "before_cursor_execute", capture)
        try:
            page = studio_summary_page(db, limit=20)
        finally:
            event.remove(engine, "before_cursor_execute", capture)

    assert len(page["items"]) == 20
    assert page["items"][0]["scene_count"] == 4
    assert page["items"][0]["downloaded_scene_count"] == 2
    page_query = next(sql for sql in statements if "from studios" in sql and "order by" in sql)
    assert "(select count(" not in page_query
    assert sum("from scenes" in sql for sql in statements) <= 1


def test_performer_summary_query_count_stays_constant_for_large_pages():
    engine, factory = _factory()
    with factory() as db:
        db.add_all(
            Performer(tpdb_id=f"p-{i}", name=f"Performer {i:04d}", is_library=True)
            for i in range(250)
        )
        db.commit()
        count = 0

        def capture(_conn, _cursor, statement, _params, _context, _many):
            nonlocal count
            if statement.lstrip().upper().startswith("SELECT"):
                count += 1

        event.listen(engine, "before_cursor_execute", capture)
        try:
            page = performer_summary_page(db, limit=100)
        finally:
            event.remove(engine, "before_cursor_execute", capture)

    assert len(page["items"]) == 100
    assert page["has_more"] is True
    assert count <= 3
