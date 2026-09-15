from __future__ import annotations


PIPELINE_STATES = frozenset(
    {
        "queued",
        "downloading",
        "downloaded",
        "verifying",
        "repairing",
        "extracting",
        "probing",
        "matching",
        "renaming",
        "moving",
        "writing_metadata",
        "cleanup",
        "imported",
        "failed",
        "paused",
        "cancelled",
    }
)

TERMINAL_STATES = frozenset({"imported", "failed", "cancelled"})

LEGACY_STATE_ALIASES = {
    "postprocessing": "verifying",
    "processing": "probing",
    "completed": "downloaded",
    "import_pending": "matching",
}

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"downloading", "paused", "cancelled", "failed"}),
    "downloading": frozenset({"downloaded", "paused", "cancelled", "failed"}),
    "downloaded": frozenset({"verifying", "failed"}),
    "verifying": frozenset({"repairing", "extracting", "probing", "failed"}),
    "repairing": frozenset({"verifying", "extracting", "failed"}),
    "extracting": frozenset({"probing", "failed"}),
    "probing": frozenset({"matching", "failed"}),
    "matching": frozenset({"renaming", "moving", "failed"}),
    "renaming": frozenset({"moving", "failed"}),
    "moving": frozenset({"writing_metadata", "failed"}),
    "writing_metadata": frozenset({"cleanup", "failed"}),
    "cleanup": frozenset({"imported", "failed"}),
    "paused": frozenset({"queued", "cancelled", "failed"}),
    "failed": frozenset({"queued"}),
    "cancelled": frozenset({"queued"}),
    "imported": frozenset(),
}


def normalize_pipeline_state(value: str | None) -> str:
    """Return the canonical durable pipeline state for a stored status label."""

    state = str(value or "").strip().casefold()
    state = LEGACY_STATE_ALIASES.get(state, state)
    if state not in PIPELINE_STATES:
        raise ValueError(f"Unknown download pipeline state: {value!r}")
    return state


def require_transition(current: str, target: str) -> str:
    """Validate and return a canonical state transition.

    State validation is intentionally pure so callers can apply it inside the
    same database transaction that persists their job update.
    """

    current_state = normalize_pipeline_state(current)
    target_state = normalize_pipeline_state(target)
    if current_state == target_state:
        return target_state
    allowed = _ALLOWED_TRANSITIONS.get(current_state, frozenset())
    if target_state not in allowed:
        raise ValueError(
            f"Invalid download pipeline transition: {current_state} -> {target_state}"
        )
    return target_state
