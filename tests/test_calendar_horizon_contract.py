from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.db import Base
from scarletx.models import Scene
from scarletx.routes.application import calendar as calendar_route


def test_calendar_default_is_not_limited_to_ninety_days():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    future = date.today() + timedelta(days=180)

    with factory() as db:
        db.add(
            Scene(
                tpdb_id="future-180",
                title="Future 180",
                content_type="scene",
                monitored=True,
                release_date=future,
            )
        )
        db.commit()
        rows = calendar_route(start=None, end=None, limit=500, db=db)

    assert [row["title"] for row in rows] == ["Future 180"]
