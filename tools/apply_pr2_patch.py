from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def patch_main() -> None:
    path = ROOT / "scarletx" / "main.py"
    source = path.read_text(encoding="utf-8")

    source = replace_once(
        source,
        "from .status_console import collect_startup_status, emit_status, render_dashboard\n",
        "from .status_console import collect_startup_status, emit_status, render_dashboard\n"
        "from .migrations import ensure_performance_indexes\n"
        "from .list_queries import performer_summary_page, scene_summary_page, studio_summary_page\n",
        "main imports",
    )
    source = replace_once(
        source,
        "        migrate_to_scarletx(db)\n        setup_token = ensure_setup_token(",
        "        migrate_to_scarletx(db)\n"
        "        with engine.begin() as connection:\n"
        "            ensure_performance_indexes(connection)\n"
        "        setup_token = ensure_setup_token(",
        "startup migration",
    )
    source = replace_once(
        source,
        "    return _scene_summary_rows(db, limit=limit, offset=offset, q=q, cursor=cursor)\n",
        "    return scene_summary_page(db, limit=limit, offset=offset, q=q, cursor=cursor)\n",
        "scene page route",
    )

    performer_pattern = re.compile(
        r'@app\.get\("/api/library/performers/page"\)\n'
        r'def performers_library_page\(.*?\n\n\n'
        r'(?=@app\.get\("/api/library/studios/page"\))',
        re.S,
    )
    performer_replacement = '''@app.get("/api/library/performers/page")
def performers_library_page(limit: int = Query(60, ge=1, le=200), offset: int = Query(0, ge=0), cursor: str | None = None, q: str | None = None, db: Session = Depends(get_session)):
    return performer_summary_page(db, limit=limit, offset=offset, cursor=cursor, q=q)


'''
    source, count = performer_pattern.subn(performer_replacement, source, count=1)
    if count != 1:
        raise RuntimeError(f"performer page route: expected one match, found {count}")

    studio_pattern = re.compile(
        r'@app\.get\("/api/library/studios/page"\)\n'
        r'def studios_library_page\(.*?\n\n\n'
        r'(?=@app\.get\("/api/library/performers/\{item_id\}/detail"\))',
        re.S,
    )
    studio_replacement = '''@app.get("/api/library/studios/page")
def studios_library_page(limit: int = Query(60, ge=1, le=200), offset: int = Query(0, ge=0), cursor: str | None = None, q: str | None = None, db: Session = Depends(get_session)):
    return studio_summary_page(db, limit=limit, offset=offset, cursor=cursor, q=q)


'''
    source, count = studio_pattern.subn(studio_replacement, source, count=1)
    if count != 1:
        raise RuntimeError(f"studio page route: expected one match, found {count}")

    path.write_text(source, encoding="utf-8")


def patch_models() -> None:
    path = ROOT / "scarletx" / "models.py"
    source = path.read_text(encoding="utf-8")

    source = replace_once(
        source,
        '    __table_args__ = (Index("ix_history_created_at", "created_at"),)\n',
        '    __table_args__ = (\n'
        '        Index("ix_history_created_at", "created_at"),\n'
        '        Index("ix_history_event_type_created_at", "event_type", "created_at"),\n'
        '    )\n',
        "history indexes",
    )
    source = replace_once(
        source,
        'class BackgroundJob(Base):\n    __tablename__ = "background_jobs"\n',
        'class BackgroundJob(Base):\n'
        '    __tablename__ = "background_jobs"\n'
        '    __table_args__ = (\n'
        '        Index("ix_background_jobs_status_kind_created_at", "status", "kind", "created_at"),\n'
        '    )\n',
        "background job indexes",
    )
    source = replace_once(
        source,
        'class TrackedDownload(Base):\n    __tablename__ = "tracked_downloads"\n',
        'class TrackedDownload(Base):\n'
        '    __tablename__ = "tracked_downloads"\n'
        '    __table_args__ = (\n'
        '        Index("ix_tracked_downloads_status_created_at", "status", "created_at"),\n'
        '        Index("ix_tracked_downloads_status_last_checked_at", "status", "last_checked_at"),\n'
        '    )\n',
        "tracked download indexes",
    )
    source = replace_once(
        source,
        'class NativeUsenetJob(Base):\n    __tablename__ = "native_usenet_jobs"\n',
        'class NativeUsenetJob(Base):\n'
        '    __tablename__ = "native_usenet_jobs"\n'
        '    __table_args__ = (\n'
        '        Index("ix_native_usenet_jobs_status_created_at", "status", "created_at"),\n'
        '        Index("ix_native_usenet_jobs_status_updated_at", "status", "updated_at"),\n'
        '    )\n',
        "native usenet indexes",
    )
    path.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    patch_main()
    patch_models()
