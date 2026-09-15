from __future__ import annotations

from datetime import timedelta

from sqlalchemy import Boolean, Column, DateTime, Integer, select

from .models import NativeUsenetJob, utcnow


ACTIVE_WATCHDOG_STATES = (
    "downloading",
    "postprocessing",
    "verifying",
    "extracting",
    "probing",
    "matching",
    "renaming",
    "moving",
    "writing_metadata",
    "cleanup",
)
DEFAULT_STALE_AFTER = timedelta(minutes=15)


def ensure_watchdog_model_columns() -> None:
    """Attach watchdog columns to upgraded/fresh declarative metadata once."""

    table = NativeUsenetJob.__table__
    if "watchdog_retries" not in table.c:
        NativeUsenetJob.watchdog_retries = Column(
            Integer,
            nullable=False,
            default=0,
            server_default="0",
        )
    if "retry_after" not in table.c:
        NativeUsenetJob.retry_after = Column(DateTime(timezone=True), nullable=True)
    if "quarantined" not in table.c:
        NativeUsenetJob.quarantined = Column(
            Boolean,
            nullable=False,
            default=False,
            server_default="0",
        )


ensure_watchdog_model_columns()


def _aware(value, reference):
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is None and getattr(reference, "tzinfo", None) is not None:
        return value.replace(tzinfo=reference.tzinfo)
    return value


def recover_stuck_native_jobs(
    session_factory,
    *,
    now=None,
    max_retries: int = 2,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
) -> dict[str, int]:
    """Requeue stale work with backoff and quarantine exhausted jobs.

    This routine is intentionally bounded and idempotent. Jobs whose retry time
    has not arrived are skipped, and unrelated healthy work is never modified.
    """

    current_time = now or utcnow()
    cutoff = current_time - stale_after
    retried = 0
    quarantined = 0
    retry_budget = max(0, int(max_retries))

    with session_factory() as db:
        jobs = db.scalars(
            select(NativeUsenetJob)
            .where(
                NativeUsenetJob.status.in_(ACTIVE_WATCHDOG_STATES),
                NativeUsenetJob.updated_at < cutoff,
                NativeUsenetJob.quarantined.is_(False),
            )
            .order_by(NativeUsenetJob.updated_at.asc(), NativeUsenetJob.created_at.asc())
            .limit(100)
        ).all()

        for job in jobs:
            retry_after = _aware(job.retry_after, current_time)
            if retry_after is not None and retry_after > current_time:
                continue

            attempts = max(0, int(job.watchdog_retries or 0))
            if attempts >= retry_budget:
                job.status = "failed"
                job.quarantined = True
                job.speed_bps = 0.0
                job.eta_seconds = None
                job.error = (
                    f"Watchdog quarantined job after {attempts} stale recovery attempts"
                )[:4000]
                quarantined += 1
                continue

            attempts += 1
            delay_seconds = min(15 * 60, 30 * (2 ** max(0, attempts - 1)))
            job.status = "queued"
            job.watchdog_retries = attempts
            job.retry_after = current_time + timedelta(seconds=delay_seconds)
            job.speed_bps = 0.0
            job.eta_seconds = None
            job.error = (
                f"Watchdog recovered stale job; retry {attempts}/{retry_budget}"
            )[:4000]
            retried += 1

        db.commit()

    return {"retried": retried, "quarantined": quarantined}
