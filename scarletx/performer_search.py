"""Local-first performer searches and lightweight persistence of search results."""
from __future__ import annotations

import json
import hashlib
import os
import threading
import time
from datetime import date
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, OperationalError

from .models import Performer
from .schemas import PerformerSearchResponse, RemotePerson


SEARCH_CACHE_ROOT = Path(os.getenv('SCARLETX_CACHE_DIR', './cache')).expanduser() / 'performer-searches'
_search_page_lock = threading.RLock()


def _search_path(settings, query: str) -> Path:
    scope = [settings.theporndb_base_url.rstrip('/'), settings.theporndb_api_key.get_secret_value(),
             query.strip().casefold()]
    return SEARCH_CACHE_ROOT / f'{hashlib.sha256(json.dumps(scope).encode()).hexdigest()}.json'


def _read_search(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or not isinstance(data.get('pages'), dict):
            return {}
        # Do not make a temporarily empty provider result permanent.
        if not data['total'] and time.time() - path.stat().st_mtime > 300:
            return {}
        for result in data['pages'].values():
            PerformerSearchResponse.model_validate(result)
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def cached_performer_search_page(settings, query: str, page: int):
    """Return one saved provider page without reconstructing it from library rows."""
    data = _read_search(_search_path(settings, query))
    raw = data.get('pages', {}).get(str(page))
    if raw is None:
        return bool(data), None
    result = PerformerSearchResponse.model_validate(raw)
    result.total = data['total']
    return True, result


def cache_performer_search_page(settings, query: str, result: PerformerSearchResponse) -> None:
    path = _search_path(settings, query)
    temp = path.with_suffix(f'.{uuid4().hex}.tmp')
    with _search_page_lock:
        try:
            data = _read_search(path) or {'pages': {}}
            data['total'] = result.total
            data['pages'][str(result.page)] = result.model_dump(mode='json')
            path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(json.dumps(data, separators=(',', ':')))
            temp.replace(path)
        except OSError:
            # Search results are already persisted in the database. A cache
            # write failure must not turn a successful provider call into 500.
            pass
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass


def _remote_performer(row: Performer) -> RemotePerson:
    values = {field: getattr(row, field) for field in RemotePerson.model_fields
              if field not in {'id', 'search_id', 'age', 'aliases', 'links'}}
    try:
        links = json.loads(row.links_json or '{}')
    except (TypeError, ValueError):
        links = {}
    age = None
    if row.birthday:
        end = row.deathday or date.today()
        age = end.year - row.birthday.year - ((end.month, end.day) < (row.birthday.month, row.birthday.day))
    return RemotePerson(
        id=row.tpdb_id, aliases=[part.strip() for part in (row.aliases or '').split(',') if part.strip()],
        links=links if isinstance(links, dict) else {}, age=age, **values,
    )


def local_performer_detail(session_factory, identifier: str) -> RemotePerson | None:
    with session_factory() as db:
        row = db.scalar(select(Performer).where(Performer.tpdb_id == identifier))
        if row is None:
            return None
        remote = _remote_performer(row)
        # Scene credits can predate library membership. Opening one must make
        # the subsequent local-profile request usable, as an external fetch does.
        if not row.is_library:
            row.is_library = True
            db.commit()
        return remote


def local_performer_search(session_factory, query: str, page: int, per_page: int = 24):
    needle = query.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    matches = or_(Performer.name.ilike(f'%{needle}%', escape='\\'),
                  Performer.aliases.ilike(f'%{needle}%', escape='\\'))
    with session_factory() as db:
        total = db.scalar(select(func.count(Performer.id)).where(matches)) or 0
        rows = db.scalars(select(Performer).where(matches).order_by(
            (func.lower(Performer.name) == query.strip().lower()).desc(),
            func.lower(Performer.name), Performer.id,
        ).offset((page - 1) * per_page).limit(per_page)).all()
        items = [_remote_performer(row) for row in rows]
        return PerformerSearchResponse(items=items, total=total, page=page, per_page=per_page)


def cache_performer_search(session_factory, people: list[RemotePerson]) -> None:
    """Save a batch without erasing richer details or changing monitoring flags."""
    for attempt in range(3):
        try:
            with session_factory() as db:
                for person in people:
                    row = db.scalar(select(Performer).where(Performer.tpdb_id == person.id))
                    if row is None:
                        row = Performer(tpdb_id=person.id, name=person.name, monitored=False)
                        db.add(row)
                    values = person.model_dump(exclude={'id', 'search_id', 'age', 'aliases', 'links'})
                    values['aliases'] = ', '.join(person.aliases) or None
                    values['links_json'] = json.dumps(person.links) if person.links else None
                    for field, value in values.items():
                        if getattr(row, field) in (None, '') and value is not None:
                            setattr(row, field, value)
                    row.is_library = True
                db.commit()
            return
        except (IntegrityError, OperationalError) as exc:
            if attempt == 2 or not any(reason in str(exc.orig).lower() for reason in (
                'unique constraint', 'database is locked', 'database is busy',
            )):
                raise
            time.sleep(.05 * (attempt + 1))
