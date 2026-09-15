from __future__ import annotations

import errno


def test_transient_provider_failures_are_retryable():
    from scarletx.failure_classification import classify_failure

    missing = classify_failure(FileNotFoundError("article unavailable"))
    timeout = classify_failure(TimeoutError("provider timed out"))

    assert missing.code == "missing_article"
    assert missing.retryable is True
    assert missing.quarantine is False
    assert timeout.code == "provider_timeout"
    assert timeout.retryable is True


def test_resource_and_payload_failures_are_terminal():
    from scarletx.failure_classification import classify_failure

    disk = classify_failure(OSError(errno.ENOSPC, "No space left on device"))
    permission = classify_failure(PermissionError("denied"))
    corrupt = classify_failure(ValueError("CRC mismatch"))

    assert (disk.code, disk.retryable, disk.quarantine) == ("disk_full", False, True)
    assert (permission.code, permission.retryable, permission.quarantine) == (
        "permission_denied", False, True
    )
    assert (corrupt.code, corrupt.retryable, corrupt.quarantine) == (
        "corrupt_payload", False, True
    )


def test_failure_detail_is_bounded_and_secret_safe():
    from scarletx.failure_classification import classify_failure

    detail = "password=super-secret " + ("x" * 2000)
    failure = classify_failure(RuntimeError(detail))

    assert len(failure.detail) <= 512
    assert "super-secret" not in failure.detail
    assert "password=" not in failure.detail.casefold()
