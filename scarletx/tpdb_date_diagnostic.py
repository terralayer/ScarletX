"""Read-only TPDB date evidence collector. Run with python -m scarletx.tpdb_date_diagnostic."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import UTC, date, datetime, timedelta
import json
import os
from pathlib import Path
import random
import sqlite3

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from .models import Performer, Scene
from .studio_policy import studio_only_reason_raw
from .tpdb import normalize_scene
from .wanted import calendar_items


def select_sample(db, count, seed):
    people = db.execute(select(Performer.tpdb_id, Performer.name).where(
        Performer.monitored.is_(True)).order_by(Performer.tpdb_id)).all()
    if count < 1:
        raise ValueError('Sample size must be positive')
    if len(people) < count:
        raise ValueError(f'Only {len(people)} monitored performers; requested {count}')
    return [dict(tpdb_id=p.tpdb_id, name=p.name) for p in random.Random(seed).sample(people, count)]


def date_fields(raw):
    # Preserve values, including nulls, without asserting that timestamps are release dates.
    return {key: value for key, value in raw.items()
            if 'date' in key.lower() or 'release' in key.lower() or key.endswith('_at')}


def scene_record(db, raw, calendar_ids, unlimited_ids, start, end):
    normalized = normalize_scene(raw)
    stored = db.scalar(select(Scene).where(Scene.tpdb_id == normalized.id))
    flags = []
    if not raw.get('date'):
        flags.append('upstream_date_missing')
    elif normalized.release_date is None:
        flags.append('date_not_parsed')
    alternate = {k: v for k, v in date_fields(raw).items()
                 if k != 'date' and ('release' in k.lower() or k.lower() in {'published_date', 'air_date'})}
    if alternate:
        flags.append('alternate_date_fields_review_required')
    if stored is None:
        status = 'not_stored'
    else:
        if stored.release_date != normalized.release_date:
            flags.append('stored_normalized_mismatch')
        if stored.id in calendar_ids:
            status = 'included'
        elif stored.id in unlimited_ids:
            status = 'limit_excluded'
        elif stored.release_date is None:
            status = 'stored_date_missing'
        elif not start <= stored.release_date <= end:
            status = 'outside_window'
        elif stored.content_type != 'scene':
            status = 'content_type_excluded'
        elif not (stored.monitored or (stored.studio and stored.studio.monitored)
                  or any(p.monitored for p in stored.performers)):
            status = 'monitoring_excluded'
        else:
            status = 'unexpected_query_exclusion'
    return {
        'scene_id': normalized.id, 'title': normalized.title,
        'raw_identifiers': {k: raw[k] for k in ('id', 'uuid', '_id') if k in raw},
        'raw_title': raw.get('title'),
        'raw_date_fields': date_fields(raw), 'selected_date_field': 'date',
        'normalized_date': normalized.release_date.isoformat() if normalized.release_date else None,
        'stored_id': stored.id if stored else None, 'stored_title': stored.title if stored else None,
        'stored_date': stored.release_date.isoformat() if stored and stored.release_date else None,
        'calendar_status': status, 'studio_policy_exclusion': studio_only_reason_raw(raw), 'flags': flags,
    }


async def run_sample(db, client, output, *, seed, count=100, start, end, limit=500, max_pages=1000):
    if start > end or limit < 1 or max_pages < 1:
        raise ValueError('Invalid date window, limit, or page bound')
    people = select_sample(db, count, seed)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    calendar_ids = {r['library_item_id'] for r in calendar_items(db, start, end, limit)}
    unlimited_ids = {r['library_item_id'] for r in calendar_items(db, start, end, None)}
    report = {
        'started_at': datetime.now(UTC).isoformat(), 'seed': seed, 'sampled_performers': count,
        'performer_ids': [p['tpdb_id'] for p in people], 'performers': people,
        'window': {'start': str(start), 'end': str(end), 'limit': limit},
        'source': 'live_http_no_cache', 'completed_performers': 0, 'errors': [],
        'calendar_matching_rows': len(unlimited_ids), 'calendar_returned_rows': len(calendar_ids),
    }
    counts, unique = Counter(), set()
    with (output / 'scenes.jsonl').open('x') as scenes, (output / 'pages.jsonl').open('x') as pages:
        for person in people:
            seen_pages = set()
            received = 0
            try:
                for page in range(1, max_pages + 1):
                    path = f"/performers/{person['tpdb_id']}/scenes"
                    response = await client.get(path, params={'page': page, 'per_page': 100})
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ValueError('Payload is not an object')
                    data, meta = payload['data'], payload.get('meta') or {}
                    if not isinstance(meta, dict):
                        raise ValueError('Metadata is not an object')
                    if meta.get('current_page') is not None and int(meta['current_page']) != page:
                        raise ValueError('Wrong page returned')
                    if not isinstance(data, list):
                        raise ValueError('Scene payload data is not a list')
                    pages.write(json.dumps({'performer_id': person['tpdb_id'], 'page': page,
                                            'fetched_at': datetime.now(UTC).isoformat(),
                                            'meta': meta, 'scene_count': len(data)}) + '\n')
                    if any(not isinstance(r, dict) for r in data):
                        raise ValueError('Scene is not an object')
                    signature = tuple(str(r.get('id') or r.get('uuid') or r.get('_id')) for r in data)
                    if signature and signature in seen_pages:
                        raise ValueError('Repeated page; pagination incomplete')
                    seen_pages.add(signature)
                    for raw in data:
                        row = scene_record(db, raw, calendar_ids, unlimited_ids, start, end)
                        row.update(performer_id=person['tpdb_id'], page=page)
                        scenes.write(json.dumps(row) + '\n')
                        if row['scene_id'] not in unique:
                            unique.add(row['scene_id'])
                            counts.update(row['flags'])
                            counts[f"calendar:{row['calendar_status']}"] += 1
                    scenes.flush()
                    pages.flush()
                    received += len(data)
                    last = meta.get('last_page')
                    if not data and last is not None and page < int(last):
                        raise ValueError('Premature empty page')
                    if (last is not None and page >= int(last)) or not data:
                        if meta.get('total') is not None and received != int(meta['total']):
                            raise ValueError('Scene count differs from advertised total')
                        report['completed_performers'] += 1
                        break
                else:
                    raise ValueError('Page bound reached; pagination incomplete')
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
                # Never include exception text containing headers, credentials, or response bodies.
                report['errors'].append({'performer_id': person['tpdb_id'], 'page': page,
                                         'type': type(exc).__name__,
                                         'http_status': exc.response.status_code
                                         if isinstance(exc, httpx.HTTPStatusError) else None})
            print(f"Performers attempted: {report['completed_performers'] + len(report['errors'])}/{count}", flush=True)
    report.update(unique_scenes=len(unique), counts=dict(counts), complete=not report['errors'],
                  finished_at=datetime.now(UTC).isoformat())
    (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def snapshot_engine(path):
    """SQLite backup gives one consistent view and cannot modify the source database."""
    source = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    snapshot = sqlite3.connect(':memory:', check_same_thread=False)
    try:
        source.backup(snapshot)
    finally:
        source.close()
    snapshot.execute('PRAGMA query_only=ON')
    return create_engine('sqlite://', creator=lambda: snapshot, poolclass=StaticPool)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, help='Path to existing live SQLite database')
    parser.add_argument('--output', required=True, type=Path, help='New output directory')
    parser.add_argument('--count', type=int, default=100)
    parser.add_argument('--seed', type=int, default=20260915)
    parser.add_argument('--start', type=date.fromisoformat, default=date.today())
    parser.add_argument('--end', type=date.fromisoformat, default=date.today() + timedelta(days=30))
    parser.add_argument('--limit', type=int, default=500)
    parser.add_argument('--max-pages', type=int, default=1000)
    args = parser.parse_args()
    key = os.environ.get('SCARLETX_TPDB_API_KEY', '')
    if not key:
        parser.error('Set SCARLETX_TPDB_API_KEY in the environment')
    engine = snapshot_engine(args.database)

    async def run():
        with Session(engine, autoflush=False) as db:
            async with httpx.AsyncClient(
                base_url=os.environ.get('SCARLETX_TPDB_BASE_URL', 'https://api.theporndb.net'),
                headers={'Authorization': f'Bearer {key}', 'Accept': 'application/json'}, timeout=30,
            ) as client:
                return await run_sample(db, client, args.output, seed=args.seed, count=args.count,
                                        start=args.start, end=args.end, limit=args.limit, max_pages=args.max_pages)
    try:
        result = asyncio.run(run())
    finally:
        engine.dispose()
    raise SystemExit(0 if result['complete'] else 2)


if __name__ == '__main__':
    main()
