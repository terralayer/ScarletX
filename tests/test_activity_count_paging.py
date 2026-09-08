from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scarletx.db import Base
from scarletx.models import TrackedDownload
from scarletx.routes import downloads


def test_activity_count_and_page_exceed_legacy_two_hundred_row_cap():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        db.add_all([
            TrackedDownload(
                nzo_id=f"job-{index:03d}",
                release_title=f"Release {index:03d}",
                status="queued",
            )
            for index in range(237)
        ])
        db.commit()

        assert downloads.activity_count(db=db) == {"active": 237}
        page = downloads.activity_page(page=5, limit=50, db=db)

    assert page["total"] == 237
    assert page["page"] == 5
    assert page["limit"] == 50
    assert len(page["items"]) == 37
    assert page["items"][0]["external_id"] == "job-200"
    assert page["items"][-1]["external_id"] == "job-236"
