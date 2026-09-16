from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

try:
    from sqlalchemy import inspect as sqlalchemy_inspect
except ImportError:  # pragma: no cover - SQLAlchemy is a runtime dependency.
    sqlalchemy_inspect = None


def normalize_title(value: str) -> str:
    value = Path(str(value or "")).stem.casefold()
    value = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", value)
    value = re.sub(r"['’ʼ]", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _loaded_relationship(scene, name: str):
    """Return relationship data without causing SQLAlchemy lazy-load queries."""
    if sqlalchemy_inspect is not None:
        try:
            state = sqlalchemy_inspect(scene)
            if name in state.unloaded:
                return None
        except Exception:
            pass
    try:
        return getattr(scene, name, None)
    except Exception:
        return None


def _scene_metadata(scene) -> tuple[str | None, date | None, tuple[str, ...]]:
    studio = _loaded_relationship(scene, "studio")
    studio_name = normalize_title(getattr(studio, "name", "")) if studio else None
    release_date = getattr(scene, "release_date", None)
    performers = _loaded_relationship(scene, "performers")
    performer_names = tuple(
        normalized
        for performer in performers or ()
        if (normalized := normalize_title(getattr(performer, "name", "")))
    )
    return studio_name or None, release_date, performer_names


@dataclass(frozen=True)
class SceneMatchCandidate:
    title: str
    scene: object
    studio: str | None
    release_date: date | None
    performers: tuple[str, ...]


@dataclass(frozen=True)
class SceneMatchIndex:
    exact: dict[str, tuple[SceneMatchCandidate, ...]]
    anchors: dict[str, tuple[SceneMatchCandidate, ...]]


@dataclass(frozen=True)
class SceneMatch:
    scene: object | None
    confidence: str
    score: int
    reasons: tuple[str, ...] = ()
    candidate_ids: tuple[object, ...] = ()

    @property
    def auto_match(self) -> bool:
        return self.scene is not None and self.confidence in {"exact", "high"}


def build_scene_match_index(scenes) -> SceneMatchIndex:
    exact: dict[str, list[SceneMatchCandidate]] = {}
    anchors: dict[str, list[SceneMatchCandidate]] = {}
    for scene in scenes:
        title = normalize_title(scene.title)
        if len(title) < 4:
            continue
        studio, release_date, performers = _scene_metadata(scene)
        candidate = SceneMatchCandidate(
            title=title,
            scene=scene,
            studio=studio,
            release_date=release_date,
            performers=performers,
        )
        exact.setdefault(title, []).append(candidate)
        words = title.split()
        if words:
            anchor = max(words, key=lambda word: (len(word), word))
            anchors.setdefault(anchor, []).append(candidate)
    return SceneMatchIndex(
        exact={key: tuple(value) for key, value in exact.items()},
        anchors={key: tuple(value) for key, value in anchors.items()},
    )


def _candidate_id(candidate: SceneMatchCandidate):
    return getattr(candidate.scene, "id", id(candidate.scene))


def _evidence(stem: str, candidate: SceneMatchCandidate) -> tuple[int, tuple[str, ...]]:
    score = 50
    reasons: list[str] = ["title"]
    if candidate.studio and candidate.studio in stem:
        score += 25
        reasons.append("studio")
    if candidate.release_date:
        full_date = normalize_title(candidate.release_date.isoformat())
        year = str(candidate.release_date.year)
        if full_date in stem or all(part in stem.split() for part in full_date.split()):
            score += 25
            reasons.append("release_date")
        elif year in stem.split():
            score += 12
            reasons.append("release_year")
    if candidate.performers:
        overlap = sum(1 for performer in candidate.performers if performer in stem)
        if overlap:
            score += min(30, 20 + (overlap - 1) * 5)
            reasons.append("performer")
    return score, tuple(reasons)


def rank_local_scene(path: Path, index: SceneMatchIndex) -> SceneMatch:
    stem = normalize_title(path.name)
    exact = index.exact.get(stem, ())
    if len(exact) == 1:
        return SceneMatch(
            scene=exact[0].scene,
            confidence="exact",
            score=100,
            reasons=("title",),
            candidate_ids=(_candidate_id(exact[0]),),
        )
    if len(exact) > 1:
        return SceneMatch(
            scene=None,
            confidence="ambiguous",
            score=100,
            reasons=("title",),
            candidate_ids=tuple(_candidate_id(candidate) for candidate in exact),
        )

    candidates: dict[object, SceneMatchCandidate] = {}
    for token in set(stem.split()):
        for candidate in index.anchors.get(token, ()):
            if candidate.title in stem:
                candidates[_candidate_id(candidate)] = candidate
    if not candidates:
        return SceneMatch(scene=None, confidence="none", score=0)

    ranked: list[tuple[int, SceneMatchCandidate, tuple[str, ...]]] = []
    for candidate in candidates.values():
        score, reasons = _evidence(stem, candidate)
        ranked.append((score, candidate, reasons))
    ranked.sort(key=lambda item: (item[0], len(item[1].title)), reverse=True)
    top_score, top_candidate, top_reasons = ranked[0]
    tied = [candidate for score, candidate, _reasons in ranked if score == top_score]
    if len(tied) > 1:
        return SceneMatch(
            scene=None,
            confidence="ambiguous",
            score=top_score,
            reasons=top_reasons,
            candidate_ids=tuple(_candidate_id(candidate) for candidate in tied),
        )
    confidence = "high" if top_score >= 70 else "medium"
    return SceneMatch(
        scene=top_candidate.scene,
        confidence=confidence,
        score=top_score,
        reasons=top_reasons,
        candidate_ids=(_candidate_id(top_candidate),),
    )


def match_local_scene(path: Path, index: SceneMatchIndex):
    """Preserve the legacy unique-title matcher while exposing confidence separately."""
    result = rank_local_scene(path, index)
    return result.scene if result.scene is not None and result.confidence != "ambiguous" else None
