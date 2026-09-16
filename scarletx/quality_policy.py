from __future__ import annotations

import json
import re
from dataclasses import dataclass

RESOLUTION_SCORE = {
    "unknown": 0,
    "480p": 100,
    "576p": 150,
    "720p": 200,
    "1080p": 300,
    "2160p": 400,
}
SOURCE_SCORE = {
    None: 0,
    "CAM": -100,
    "TELESYNC": -80,
    "HDTV": 10,
    "WEBRip": 20,
    "WEB-DL": 30,
    "BluRay": 40,
    "REMUX": 50,
}
CODEC_SCORE = {
    None: 0,
    "mpeg2video": 0,
    "h264": 10,
    "avc": 10,
    "vp9": 15,
    "hevc": 20,
    "h265": 20,
    "av1": 25,
}


@dataclass(frozen=True)
class QualityFacts:
    resolution: str = "unknown"
    source: str | None = None
    video_codec: str | None = None
    bitrate_bps: int | None = None
    size_bytes: int | None = None
    release_group: str | None = None


@dataclass(frozen=True)
class UpgradeDecision:
    upgrade: bool
    reason: str
    current_score: int
    candidate_score: int


def _resolution_from_title(title: str) -> str:
    value = title.casefold()
    for pattern, label in (
        (r"(?:^|[. _-])2160p?(?:[. _-]|$)|\b4k\b|\buhd\b", "2160p"),
        (r"(?:^|[. _-])1080p?(?:[. _-]|$)", "1080p"),
        (r"(?:^|[. _-])720p?(?:[. _-]|$)", "720p"),
        (r"(?:^|[. _-])576p?(?:[. _-]|$)", "576p"),
        (r"(?:^|[. _-])480p?(?:[. _-]|$)", "480p"),
    ):
        if re.search(pattern, value, re.I):
            return label
    return "unknown"


def _source_from_title(title: str) -> str | None:
    for pattern, label in (
        (r"\bremux\b", "REMUX"),
        (r"\bblu[ ._-]?ray\b|\bbdrip\b|\bbrrip\b", "BluRay"),
        (r"\bweb[ ._-]?dl\b|\bwebdl\b", "WEB-DL"),
        (r"\bweb[ ._-]?rip\b|\bwebrip\b", "WEBRip"),
        (r"\bhdtv\b", "HDTV"),
        (r"\btelesync\b|(?:^|[. _-])ts(?:[. _-]|$)", "TELESYNC"),
        (r"\bcam\b", "CAM"),
    ):
        if re.search(pattern, title, re.I):
            return label
    return None


def _release_group_from_title(title: str) -> str | None:
    stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", title.strip())
    match = re.search(r"-([A-Za-z0-9][A-Za-z0-9._]{1,31})$", stem)
    return match.group(1) if match else None


def facts_from_release(
    title: str,
    *,
    size_bytes: int | None = None,
    video_codec: str | None = None,
    bitrate_bps: int | None = None,
) -> QualityFacts:
    return QualityFacts(
        resolution=_resolution_from_title(title),
        source=_source_from_title(title),
        video_codec=video_codec.casefold() if video_codec else None,
        bitrate_bps=bitrate_bps,
        size_bytes=size_bytes,
        release_group=_release_group_from_title(title),
    )


def quality_badges(facts: QualityFacts) -> list[str]:
    badges = [facts.resolution]
    if facts.source:
        badges.append(facts.source)
    if facts.video_codec:
        badges.append(facts.video_codec.upper())
    if facts.bitrate_bps is not None and facts.bitrate_bps > 0:
        badges.append(f"{facts.bitrate_bps / 1_000_000:.1f} Mbps")
    if facts.release_group:
        badges.append(facts.release_group)
    return badges


def _allowed_resolutions(profile) -> set[str]:
    try:
        values = json.loads(getattr(profile, "allowed_qualities_json", "[]") or "[]")
    except (TypeError, json.JSONDecodeError):
        values = []
    return {str(value).strip().casefold() for value in values if str(value).strip()}


def _fits_profile(profile, facts: QualityFacts) -> bool:
    allowed = _allowed_resolutions(profile)
    if allowed and facts.resolution.casefold() not in allowed:
        return False
    size_mb = facts.size_bytes / 1024**2 if facts.size_bytes is not None else None
    minimum = getattr(profile, "min_size_mb", None)
    maximum = getattr(profile, "max_size_mb", None)
    if size_mb is not None and minimum is not None and size_mb < float(minimum):
        return False
    if size_mb is not None and maximum is not None and size_mb > float(maximum):
        return False
    return True


def quality_score(facts: QualityFacts) -> int:
    score = RESOLUTION_SCORE.get(facts.resolution.casefold(), 0) * 1000
    score += SOURCE_SCORE.get(facts.source, 0) * 100
    score += CODEC_SCORE.get(facts.video_codec.casefold() if facts.video_codec else None, 0) * 10
    if facts.bitrate_bps is not None and facts.bitrate_bps > 0:
        score += min(facts.bitrate_bps // 100_000, 500)
    return score


def evaluate_upgrade(profile, current: QualityFacts, candidate: QualityFacts) -> UpgradeDecision:
    current_score = quality_score(current)
    candidate_score = quality_score(candidate)

    if not bool(getattr(profile, "upgrades_allowed", True)):
        return UpgradeDecision(False, "upgrades_disabled", current_score, candidate_score)
    if not _fits_profile(profile, candidate):
        return UpgradeDecision(False, "candidate_outside_profile", current_score, candidate_score)

    cutoff = str(getattr(profile, "cutoff_quality", "") or "").casefold()
    cutoff_score = RESOLUTION_SCORE.get(cutoff, 0)
    current_resolution_score = RESOLUTION_SCORE.get(current.resolution.casefold(), 0)
    if cutoff_score and current_resolution_score >= cutoff_score:
        return UpgradeDecision(False, "cutoff_reached", current_score, candidate_score)

    if candidate_score <= current_score:
        return UpgradeDecision(False, "not_better", current_score, candidate_score)
    return UpgradeDecision(True, "better_quality", current_score, candidate_score)
