from datetime import UTC, datetime
from typing import Literal
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session
from .download_schedule import DownloadSchedule, configured_schedule, schedule_state
from .models import AppSetting
from .operations import backup_reminder, cleanup_preview, storage_overview
from .settings_store import load_database_settings, set_setting

router = APIRouter(prefix="/api/operations")


@router.get("/storage")
def storage(db: Session = Depends(get_session)):
    return storage_overview(db, load_database_settings(db))


@router.get("/backup-reminder")
def reminder(db: Session = Depends(get_session)):
    return backup_reminder(db, load_database_settings(db))


@router.get("/cleanup")
def cleanup(
    category: Literal["duplicates", "missing", "unmatched"] = "duplicates",
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_session),
):
    return cleanup_preview(db, category, limit, offset)


@router.get("/download-schedule")
def read_schedule(db: Session = Depends(get_session)):
    settings = load_database_settings(db)
    rule = configured_schedule(settings)
    return dict(
        rule=rule.model_dump(), state=schedule_state(rule, base_limit=settings.native_usenet_speed_limit_mb_s)
    )


@router.patch("/download-schedule")
def save_schedule(rule: DownloadSchedule, db: Session = Depends(get_session)):
    set_setting(db, "download_schedule_json", rule.model_dump_json())
    return read_schedule(db)


_CONNECTION_KEYS = {
    "metadata": ("theporndb_api_key", "theporndb_base_url"),
    "indexers": ("newznab_indexers_json",),
    "downloads": ("native_usenet_providers_json", "native_usenet_enabled"),
}


def _connection_snapshot(db):
    settings = load_database_settings(db)
    versions = {
        row.key: row.updated_at.isoformat()
        for row in db.scalars(
            select(AppSetting).where(
                AppSetting.key.in_([key for keys in _CONNECTION_KEYS.values() for key in keys])
            )
        )
    }
    steps = [
        dict(id="metadata", title="TPDB", configured=bool(settings.theporndb_api_key.get_secret_value())),
        dict(
            id="indexers",
            title="Indexers",
            configured=any(item.enabled for item in settings.newznab_indexers()),
        ),
        dict(
            id="downloads",
            title="Usenet providers",
            configured=settings.native_usenet_enabled
            and any(item.enabled and item.host for item in settings.native_usenet_providers()),
        ),
    ]
    for step in steps:
        step["revision"] = "|".join(versions.get(key, "") for key in _CONNECTION_KEYS[step["id"]])
    return settings, steps


@router.get("/connections")
def connections(db: Session = Depends(get_session)):
    return dict(steps=_connection_snapshot(db)[1])


@router.post("/connections/{kind}/test")
async def test_connection(
    kind: Literal["metadata", "indexers", "downloads"], db: Session = Depends(get_session)
):
    from .newznab import NewznabClient
    from .tpdb import ThePornDBClient
    from .usenet.worker import test_provider

    settings, steps = _connection_snapshot(db)
    step = next(item for item in steps if item["id"] == kind)
    if not step["configured"]:
        raise HTTPException(409, "Save and enable this connection first.")
    try:
        # No cached metadata success: this explicitly checks the saved credential.
        if kind == "metadata":
            async with ThePornDBClient(
                settings.theporndb_api_key.get_secret_value(), settings.theporndb_base_url
            ) as client:
                response = await client.client.get("/scenes", params={"per_page": 1})
                response.raise_for_status()
        elif kind == "indexers":
            for item in settings.newznab_indexers():
                if item.enabled:
                    async with NewznabClient(item) as client:
                        if not await client.caps():
                            raise RuntimeError("Indexer did not return valid capabilities")
        else:
            for item in settings.native_usenet_providers():
                if item.enabled:
                    await asyncio.to_thread(test_provider, item)
    except Exception as exc:
        # Provider exceptions may include URLs or credentials; do not echo them.
        raise HTTPException(
            502, "Connection test failed. Check saved credentials, address and network access."
        ) from exc
    return dict(ok=True, revision=step["revision"], tested_at=datetime.now(UTC).isoformat())
