from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scarletx.db import Base
from scarletx.models import AppSetting
from scarletx.settings_store import seed_database_settings


def test_legacy_fifty_connection_default_is_upgraded_once():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        db.add(AppSetting(key="native_usenet_max_connections", value="50", is_secret=False))
        db.commit()

        seed_database_settings(db)
        db.commit()

        assert db.get(AppSetting, "native_usenet_max_connections").value == "200"
        assert db.get(AppSetting, "native_usenet_connection_cap_200_migrated").value == "true"
