"""Local-first studio metadata, retaining the production-studio policy."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from .models import Studio
from .schemas import RemoteStudio, StudioSearchResponse
from .studio_policy import blocked_library_studio_ids, is_allowed_tpdb_site_raw


SEARCH_CACHE_ROOT = Path(os.getenv('SCARLETX_CACHE_DIR', './cache')).expanduser() / 'studio-searches'
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
        # Empty searches should be retried later; successful pages stay local.
        if not data['total'] and time.time() - path.stat().st_mtime > 300:
            return {}
        for result in data['pages'].values():
            StudioSearchResponse.model_validate(result)
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def cached_studio_search_page(settings, query: str, page: int):
    """Keep provider ordering and totals separate from incomplete library matches."""
    data = _read_search(_search_path(settings, query))
    raw = data.get('pages', {}).get(str(page))
    if raw is None:
        return bool(data), None
    result = StudioSearchResponse.model_validate(raw)
    result.total = data['total']
    result.items = [item for item in result.items if is_allowed_tpdb_site_raw(item.model_dump())]
    return True, result


def cache_studio_search_page(settings, query: str, result: StudioSearchResponse) -> None:
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
            # The committed library metadata remains usable if the disk cache
            # is unavailable; never fail a successful provider response for it.
            pass
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass


def _remote_studio(row: Studio) -> RemoteStudio:
    return RemoteStudio(id=row.tpdb_id, **{
        field: getattr(row, field) for field in RemoteStudio.model_fields
        if field not in {'id', 'search_id'}
    })


def local_studio_detail(session_factory, identifier: str) -> RemoteStudio | None:
    with session_factory() as db:
        row = db.scalar(select(Studio).where(Studio.tpdb_id == identifier))
        if row is None:
            return None
        remote = _remote_studio(row)
        if not is_allowed_tpdb_site_raw(remote.model_dump()):
            return None
        if not row.is_library:
            row.is_library = True
            db.commit()
        return remote


def local_studio_search(session_factory, query: str, page: int, per_page: int = 24):
    needle = query.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    with session_factory() as db:
        matches = (
            Studio.name.ilike(f'%{needle}%', escape='\\'),
            Studio.id.not_in(blocked_library_studio_ids(db)),
        )
        total = db.scalar(select(func.count(Studio.id)).where(*matches)) or 0
        rows = db.scalars(select(Studio).where(*matches).order_by(
            (func.lower(Studio.name) == query.strip().lower()).desc(),
            func.lower(Studio.name), Studio.id,
        ).offset((page - 1) * per_page).limit(per_page)).all()
        return StudioSearchResponse(items=[_remote_studio(row) for row in rows],
                                    total=total, page=page, per_page=per_page)


def cache_studio_search(session_factory, studios: list[RemoteStudio]) -> None:
    """Save fetched metadata without erasing rich fields or changing monitoring."""
    for attempt in range(3):
        try:
            with session_factory() as db:
                for studio in studios:
                    if not is_allowed_tpdb_site_raw(studio.model_dump()):
                        continue
                    row = db.scalar(select(Studio).where(Studio.tpdb_id == studio.id))
                    if row is None:
                        row = Studio(tpdb_id=studio.id, name=studio.name, monitored=False)
                        db.add(row)
                    for field, value in studio.model_dump(exclude={'id', 'search_id'}).items():
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
