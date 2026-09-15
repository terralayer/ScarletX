from __future__ import annotations

import pytest


def test_pipeline_state_vocabulary_covers_end_to_end_import():
    from scarletx.download_state import PIPELINE_STATES

    required = {
        "queued", "downloading", "downloaded", "verifying", "extracting",
        "probing", "matching", "renaming", "moving", "writing_metadata",
        "cleanup", "imported", "failed",
    }
    assert required <= PIPELINE_STATES


def test_pipeline_state_machine_accepts_happy_path_and_rejects_skip():
    from scarletx.download_state import require_transition

    path = [
        "queued", "downloading", "downloaded", "verifying", "extracting",
        "probing", "matching", "renaming", "moving", "writing_metadata",
        "cleanup", "imported",
    ]
    for current, target in zip(path, path[1:]):
        assert require_transition(current, target) == target

    with pytest.raises(ValueError):
        require_transition("downloading", "imported")


def test_legacy_postprocessing_state_normalizes_without_losing_compatibility():
    from scarletx.download_state import normalize_pipeline_state

    assert normalize_pipeline_state("postprocessing") == "verifying"
    assert normalize_pipeline_state("processing") == "probing"
