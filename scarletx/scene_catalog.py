"""Durable, paginated scene discovery for locally cached profile pages."""
from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime

from sqlalchemy import func, select

from .db import SessionLocal
from .entity_hydration import _entity_scene_summaries, cache_entity_scene_summaries
from .metadata import metadata_client
from .models import BackgroundJob, utcnow

_queue_lock = threading.Lock()
_fetch_slots = asyncio.Semaphore(2)


def _latest_job(db, entity_type, identifier, *, statuses=None):
    statement = select(BackgroundJob).where(
        BackgroundJob.kind == f"{entity_type}_scene_catalog",
        func.json_valid(BackgroundJob.payload) == 1,
        func.json_extract(BackgroundJob.payload, '$.identifier') == identifier,
    )
    if statuses:
        statement = statement.where(BackgroundJob.status.in_(statuses))
    return db.scalar(statement.order_by(BackgroundJob.id.desc()).limit(1))


def _iso_utc(value: datetime | None):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat()


def _status(job, last_success):
    payload = json.loads(job.payload) if job else {}
    return {
        'job_id': job.id if job else None,
        'status': job.status if job else 'not_started',
        'scenes_cached': payload.get('scenes_cached', 0),
        'pages_fetched': payload.get('pages_fetched', 0),
        'provider_total': payload.get('provider_total'),
        'error': job.error if job else None,
        'queued_at': _iso_utc(job.created_at) if job else None,
        'finished_at': _iso_utc(job.finished_at) if job else None,
        'last_success_at': _iso_utc(last_success.finished_at) if last_success else None,
    }


def scene_catalog_status(db, entity_type, identifier):
    latest = _latest_job(db, entity_type, identifier)
    last_success = _latest_job(db, entity_type, identifier, statuses=('completed',))
    return _status(latest, last_success)


def ensure_scene_catalog(db, tasks, entity_type, identifier, settings, *, force=False):
    if entity_type not in {'performer', 'studio'}:
        raise ValueError('Unsupported entity type')
    with _queue_lock:
        previous = _latest_job(db, entity_type, identifier)
        # Failed scans remain visible until Refresh is used; never retry forever.
        if previous and (not force or previous.status in {'queued', 'running'}):
            return scene_catalog_status(db, entity_type, identifier)
        job = BackgroundJob(kind=f'{entity_type}_scene_catalog', payload=json.dumps({
            'entity_type': entity_type, 'identifier': identifier,
        }))
        db.add(job)
        db.commit()
        db.refresh(job)
        tasks.add_task(run_scene_catalog, job.id, entity_type, identifier, settings)
        return scene_catalog_status(db, entity_type, identifier)


def _save_progress(job_id, **changes):
    with SessionLocal() as db:
        job = db.get(BackgroundJob, job_id)
        if job is None:
            return
        payload = json.loads(job.payload)
        for field in ('status', 'error'):
            if field in changes:
                setattr(job, field, changes.pop(field))
        payload.update(changes)
        job.payload = json.dumps(payload)
        if job.status in {'completed', 'failed'}:
            job.finished_at = utcnow()
        db.commit()


async def run_scene_catalog(job_id, entity_type, identifier, settings):
    async with _fetch_slots:
        try:
            await asyncio.to_thread(_save_progress, job_id, status='running', error=None)
            saved_ids = set()

            async def save_page(scenes, page, provider_total):
                ids = await asyncio.to_thread(
                    cache_entity_scene_summaries, scenes, False,
                    entity_type=entity_type, identifier=identifier,
                )
                saved_ids.update(ids)
                await asyncio.to_thread(_save_progress, job_id,
                    scenes_cached=len(saved_ids), pages_fetched=page, provider_total=provider_total)

            # Local profiles remain usable during outages, but only authoritative
            # provider pages may establish the durable completeness marker.
            async with metadata_client(settings, fresh=True) as provider:
                await _entity_scene_summaries(provider, entity_type, identifier, on_page=save_page)
            await asyncio.to_thread(_save_progress, job_id, status='completed')
        except Exception as exc:
            await asyncio.to_thread(_save_progress, job_id, status='failed', error=str(exc)[:1000])
