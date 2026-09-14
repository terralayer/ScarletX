from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.db import Base
from scarletx.models import Scene, Studio
from scarletx.routes.application import calendar as calendar_route


def test_calendar_explicit_end_can_look_past_default_thirty_days():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    today = date.today()

    with factory() as db:
        studio = Studio(tpdb_id="future-studio", name="Future Studio", monitored=True, is_library=True)
        db.add(studio)
        db.flush()
        db.add(
            Scene(
                tpdb_id="future-180",
                title="Future 180",
                content_type="scene",
                monitored=True,
                release_date=today + timedelta(days=180),
                studio_id=studio.id,
            )
        )
        db.commit()
        rows = calendar_route(
            start=None,
            end=today + timedelta(days=365),
            limit=500,
            db=db,
        )

    assert [row["title"] for row in rows] == ["Future 180"]
