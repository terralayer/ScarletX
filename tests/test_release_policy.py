from types import SimpleNamespace

import pytest


def test_rejects_release_below_500_mib():
    from scarletx.release_policy import MIN_RELEASE_BYTES, release_rejection_reason

    assert release_rejection_reason("Studio Scene 1080p", MIN_RELEASE_BYTES - 1) == "Release is smaller than 500 MiB"


def test_accepts_release_at_boundary_and_with_unknown_size():
    from scarletx.release_policy import MIN_RELEASE_BYTES, release_rejection_reason

    assert release_rejection_reason("Studio Scene 1080p", MIN_RELEASE_BYTES) is None
    assert release_rejection_reason("Studio Scene 1080p", None) is None


@pytest.mark.parametrize(
    "title",
    ["Scene SAMPLE", "Scene trailer", "Scene image set", "Scene Photos", "Scene screenshots"],
)
def test_rejects_sample_and_image_release_titles(title):
    from scarletx.release_policy import MIN_RELEASE_BYTES, release_rejection_reason

    assert release_rejection_reason(title, MIN_RELEASE_BYTES) == "Release title identifies sample or image content"


def test_title_filter_uses_tokens_instead_of_substrings():
    from scarletx.release_policy import MIN_RELEASE_BYTES, release_rejection_reason

    assert release_rejection_reason("Studio Example Imagesque 1080p", MIN_RELEASE_BYTES) is None


def test_automatic_release_selection_skips_rejected_release():
    from scarletx.automation import choose_best_release
    from scarletx.release_policy import MIN_RELEASE_BYTES

    scene = SimpleNamespace(title="A Great Scene", studio=SimpleNamespace(name="Studio"))
    profile = SimpleNamespace(
        allowed_qualities_json='["1080p"]', cutoff_quality="1080p",
        min_size_mb=None, max_size_mb=None, preferred_terms_json="[]",
        rejected_terms_json="[]", upgrades_allowed=True,
    )
    small = SimpleNamespace(title="Studio A Great Scene 1080p", size=MIN_RELEASE_BYTES - 1, published_at=None)
    sample = SimpleNamespace(title="Studio A Great Scene Sample 1080p", size=MIN_RELEASE_BYTES, published_at=None)

    assert choose_best_release(scene, [small, sample], profile) is None
