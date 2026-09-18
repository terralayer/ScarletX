"""Persistent, disposable canonical-path lookup with filesystem invalidation."""

from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.dialects.sqlite import insert

from .library_scanner import normalized_path
from .models import ScanPathDirectory, ScanPathIndex


def _directory_signature(directory):
    resolved = normalized_path(directory)
    try:
        stat = Path(directory).stat()
        identity = (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns)
    except OSError as exc:
        identity = ("unavailable", exc.errno)
    return json.dumps((os.getcwd(), resolved, identity))


def _refresh(db, model):
    kind = model.__tablename__
    cache = ScanPathIndex
    # Handles ORM changes and direct SQL writes/deletes without relying on hooks.
    db.flush()
    db.execute(
        delete(cache)
        .where(
            cache.source_kind == kind,
            ~exists(select(model.id).where(model.id == cache.source_id, model.path == cache.source_path)),
        )
        .execution_options(synchronize_session=False)
    )
    for path, previous in db.execute(
        select(ScanPathDirectory.path, ScanPathDirectory.signature).where(
            ScanPathDirectory.source_kind == kind
        )
    ):
        signature = _directory_signature(path)
        if signature != previous:
            db.execute(
                delete(cache)
                .where(cache.source_kind == kind, cache.directory == path)
                .execution_options(synchronize_session=False)
            )
            db.execute(
                delete(ScanPathDirectory)
                .where(ScanPathDirectory.source_kind == kind, ScanPathDirectory.path == path)
                .execution_options(synchronize_session=False)
            )
    # Individual symlink chains can change outside their containing directory.
    for row in db.execute(
        select(cache.source_id, cache.source_path, cache.canonical_path).where(
            cache.source_kind == kind, cache.file_alias.is_(True)
        )
    ):
        resolved = normalized_path(row.source_path)
        if resolved != row.canonical_path:
            db.execute(
                update(cache)
                .where(cache.source_kind == kind, cache.source_id == row.source_id)
                .values(canonical_path=resolved)
                .execution_options(synchronize_session=False)
            )
    after_id = 0
    while True:
        rows = db.execute(
            select(model.id, model.path)
            .where(
                model.id > after_id,
                ~exists(
                    select(cache.source_id).where(cache.source_kind == kind, cache.source_id == model.id)
                ),
            )
            .order_by(model.id)
            .limit(500)
        ).all()
        if not rows:
            break
        records = []
        directories = {}
        for source_id, path in rows:
            directory = os.path.dirname(os.path.abspath(os.path.expanduser(path)))
            if directory not in directories:
                directories[directory] = _directory_signature(directory)
            canonical = normalized_path(path)
            parent_canonical = json.loads(directories[directory])[1]
            records.append(
                dict(
                    source_kind=kind,
                    source_id=source_id,
                    source_path=path,
                    directory=directory,
                    canonical_path=canonical,
                    file_alias=canonical != str(Path(parent_canonical) / Path(path).name),
                )
            )
        db.execute(insert(cache).values(records).on_conflict_do_nothing())
        for directory, signature in directories.items():
            db.execute(
                insert(ScanPathDirectory)
                .values(source_kind=kind, path=directory, signature=signature)
                .on_conflict_do_nothing()
            )
        after_id = rows[-1].id
    db.execute(
        delete(ScanPathDirectory)
        .where(
            ScanPathDirectory.source_kind == kind,
            ~exists(
                select(cache.source_id).where(
                    cache.source_kind == kind, cache.directory == ScanPathDirectory.path
                )
            ),
        )
        .execution_options(synchronize_session=False)
    )


def scoped_records(db, model, prefixes, *, refresh=True):
    if not prefixes:
        return
    # Preserve compatibility with custom non-SQLite deployments without cache writes.
    if db.get_bind().dialect.name != "sqlite":
        for batch in db.execute(select(model.id, model.path).execution_options(yield_per=500)).partitions(
            500
        ):
            ids = [row.id for row in batch if normalized_path(row.path).startswith(prefixes)]
            if ids:
                yield from db.scalars(select(model).where(model.id.in_(ids)))
        return
    if refresh:
        _refresh(db, model)
    # Binary ranges use the composite index; LIKE can be case-insensitive on SQLite.
    ranges = [
        (
            (ScanPathIndex.canonical_path >= prefix)
            & (ScanPathIndex.canonical_path < prefix[:-1] + chr(ord(prefix[-1]) + 1))
        )
        for prefix in prefixes
    ]
    yield from db.scalars(
        select(model)
        .join(
            ScanPathIndex,
            (ScanPathIndex.source_id == model.id) & (ScanPathIndex.source_kind == model.__tablename__),
        )
        .where(or_(*ranges))
        .execution_options(yield_per=500)
    )


def refresh_scan_path_index(session_factory):
    from .models import MediaFile, UnmatchedMediaFile

    # Commit derived-cache writes before the potentially long filesystem scan.
    for model in (MediaFile, UnmatchedMediaFile):
        with session_factory() as db:
            if db.get_bind().dialect.name == "sqlite":
                _refresh(db, model)
                db.commit()
