from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


def normalize_title(value: str) -> str:
    value = Path(str(value or "")).stem.casefold()
    value = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", value)
    value = re.sub(r"['’ʼ]", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


@dataclass(frozen=True)
class SceneMatchIndex:
    exact: dict[str, tuple]
    anchors: dict[str, tuple]


def build_scene_match_index(scenes) -> SceneMatchIndex:
    exact: dict[str, list] = {}
    anchors: dict[str, list] = {}
    for scene in scenes:
        title = normalize_title(scene.title)
        if len(title) < 4:
            continue
        exact.setdefault(title, []).append(scene)
        words = title.split()
        if words:
            anchor = max(words, key=lambda word: (len(word), word))
            anchors.setdefault(anchor, []).append((title, scene))
    return SceneMatchIndex(
        exact={key: tuple(value) for key, value in exact.items()},
        anchors={key: tuple(value) for key, value in anchors.items()},
    )


def match_local_scene(path: Path, index: SceneMatchIndex):
    stem = normalize_title(path.name)
    exact = index.exact.get(stem, ())
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None

    candidates: dict[int, tuple[int, object]] = {}
    for token in set(stem.split()):
        for title, scene in index.anchors.get(token, ()):
            if title in stem:
                candidates[id(scene)] = (len(title), scene)
    if not candidates:
        return None
    ranked = sorted(candidates.values(), key=lambda item: item[0], reverse=True)
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None
    return ranked[0][1]
