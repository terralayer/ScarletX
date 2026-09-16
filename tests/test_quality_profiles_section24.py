from __future__ import annotations

from types import SimpleNamespace


def _profile(**overrides):
    values = {
        "allowed_qualities_json": '["2160p","1080p","720p"]',
        "cutoff_quality": "2160p",
        "min_size_mb": 500.0,
        "max_size_mb": 20000.0,
        "upgrades_allowed": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_quality_facts_parse_source_codec_bitrate_group_and_badges():
    from scarletx.quality_policy import facts_from_release, quality_badges

    facts = facts_from_release(
        "Studio.Scene.1080p.WEB-DL.HEVC-GROUP",
        size_bytes=2 * 1024**3,
        video_codec="hevc",
        bitrate_bps=12_500_000,
    )

    assert facts.resolution == "1080p"
    assert facts.source == "WEB-DL"
    assert facts.video_codec == "hevc"
    assert facts.release_group == "GROUP"
    assert quality_badges(facts) == ["1080p", "WEB-DL", "HEVC", "12.5 Mbps", "GROUP"]


def test_profile_size_quality_and_upgrade_toggle_are_enforced():
    from scarletx.quality_policy import QualityFacts, evaluate_upgrade

    current = QualityFacts(resolution="720p", source="WEBRip", size_bytes=900 * 1024**2)
    candidate = QualityFacts(resolution="1080p", source="WEB-DL", size_bytes=2 * 1024**3)

    assert evaluate_upgrade(_profile(upgrades_allowed=False), current, candidate).upgrade is False
    assert evaluate_upgrade(_profile(min_size_mb=3000), current, candidate).upgrade is False
    assert evaluate_upgrade(_profile(allowed_qualities_json='["720p"]'), current, candidate).upgrade is False


def test_cutoff_stops_future_upgrades_after_current_quality_reaches_it():
    from scarletx.quality_policy import QualityFacts, evaluate_upgrade

    current = QualityFacts(resolution="1080p", source="WEB-DL", size_bytes=2 * 1024**3)
    candidate = QualityFacts(resolution="2160p", source="REMUX", size_bytes=10 * 1024**3)
    decision = evaluate_upgrade(_profile(cutoff_quality="1080p"), current, candidate)

    assert decision.upgrade is False
    assert decision.reason == "cutoff_reached"


def test_same_resolution_can_upgrade_for_better_source_codec_and_bitrate():
    from scarletx.quality_policy import QualityFacts, evaluate_upgrade

    current = QualityFacts(
        resolution="1080p",
        source="WEBRip",
        video_codec="h264",
        bitrate_bps=5_000_000,
        size_bytes=2 * 1024**3,
    )
    candidate = QualityFacts(
        resolution="1080p",
        source="WEB-DL",
        video_codec="hevc",
        bitrate_bps=9_000_000,
        size_bytes=3 * 1024**3,
    )
    decision = evaluate_upgrade(_profile(), current, candidate)

    assert decision.upgrade is True
    assert decision.candidate_score > decision.current_score
