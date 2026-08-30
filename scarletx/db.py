from collections.abc import Generator
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

class Base(DeclarativeBase):
    pass

DATABASE_URL = os.getenv("SCARLETX_DATABASE_URL", "sqlite:///./scarletx.db")

def _engine_kwargs(url: str) -> dict:
    if not url.startswith("sqlite"):
        return {"pool_pre_ping": True}
    kwargs = {
        "connect_args": {"check_same_thread": False},
        "pool_pre_ping": True,
    }
    # SQLAlchemy already pools file-backed SQLite connections; give ScarletX a
    # slightly wider read pool so UI/API reads do not queue behind downloader and
    # scanner sessions. Do not change in-memory SQLite's special pool semantics.
    if ":memory:" not in url:
        kwargs.update(pool_size=10, max_overflow=20, pool_timeout=30)
    return kwargs

engine = create_engine(DATABASE_URL, **_engine_kwargs(DATABASE_URL))

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL lets the 750 ms live queue read while the downloader persists progress.
        # NORMAL sync is durable enough for transient progress counters and avoids an
        # fsync-heavy commit path that throttled high-segment NZBs.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        # Favor a larger read cache and memory-backed temp work. These are per
        # connection and keep library paging/sorting from repeatedly hitting disk.
        cursor.execute("PRAGMA cache_size=-65536")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA mmap_size=268435456")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
