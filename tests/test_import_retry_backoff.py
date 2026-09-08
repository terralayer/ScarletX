from datetime import timedelta

from scarletx.models import TrackedDownload, utcnow


def test_import_retry_backoff_delays_second_attempt():
    from scarletx.download_processing import _import_retry_ready

    tracked = TrackedDownload(
        nzo_id="job-1",
        release_title="Scene",
        status="import_pending",
        error="[import-attempt 1/3] FileImportError: no primary video",
        last_checked_at=utcnow(),
    )

    assert _import_retry_ready(tracked, now=tracked.last_checked_at + timedelta(seconds=10)) is False
    assert _import_retry_ready(tracked, now=tracked.last_checked_at + timedelta(seconds=31)) is True


def test_import_retry_backoff_delays_third_attempt_longer():
    from scarletx.download_processing import _import_retry_ready

    tracked = TrackedDownload(
        nzo_id="job-2",
        release_title="Scene",
        status="import_pending",
        error="[import-attempt 2/3] FileImportError: still broken",
        last_checked_at=utcnow(),
    )

    assert _import_retry_ready(tracked, now=tracked.last_checked_at + timedelta(seconds=60)) is False
    assert _import_retry_ready(tracked, now=tracked.last_checked_at + timedelta(seconds=121)) is True


def test_import_failure_attempt_parser_and_terminal_state():
    from scarletx.download_processing import IMPORT_MAX_ATTEMPTS, _import_failure_attempt

    assert IMPORT_MAX_ATTEMPTS == 3
    assert _import_failure_attempt(None) == 0
    assert _import_failure_attempt("plain old error") == 0
    assert _import_failure_attempt("[import-attempt 2/3] OSError: disk offline") == 2
    assert _import_failure_attempt("[import-attempt 3/3] FileImportError: bad payload") == 3
