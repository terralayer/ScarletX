from __future__ import annotations

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.db import Base
from scarletx.list_queries import scene_summary_page
from scarletx.models import Scene


def test_repeated_library_searches_do_not_reprobe_fts_schema():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with engine.begin() as conn:
        conn.execute(text("CREATE VIRTUAL TABLE scene_search USING fts5(title)"))

    with factory() as db:
        scene = Scene(tpdb_id="search-1", title="Fast Search Scene", content_type="scene")
        db.add(scene)
        db.commit()
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO scene_search(rowid, title) VALUES (:id, :title)"),
                {"id": scene.id, "title": scene.title},
            )

        schema_probes = 0

        def capture(_conn, _cursor, statement, _params, _context, _many):
            nonlocal schema_probes
            if "sqlite_master" in statement.lower():
                schema_probes += 1

        event.listen(engine, "before_cursor_execute", capture)
        try:
            first = scene_summary_page(db, limit=20, q="Fast Search")
            second = scene_summary_page(db, limit=20, q="Fast Search")
        finally:
            event.remove(engine, "before_cursor_execute", capture)

    assert [row["title"] for row in first["items"]] == ["Fast Search Scene"]
    assert [row["title"] for row in second["items"]] == ["Fast Search Scene"]
    assert schema_probes == 1
