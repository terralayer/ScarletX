from __future__ import annotations

from pathlib import Path

import pytest

from scarletx.schemas import RemoteScene, RemoteStudio, SearchResponse


ROOT = Path(__file__).parents[1]
FRONTEND = ROOT / "frontend"


def test_late_frontend_overrides_do_not_replace_core_renderers():
    studio = (FRONTEND / "studio_art_overrides.js").read_text(encoding="utf-8")
    dashboard = (FRONTEND / "dashboard_settings_overrides.js").read_text(encoding="utf-8")

    assert "studioLink=function" not in studio
    assert "entityCard=function" not in studio
    assert "dashboard=async function" not in dashboard
    assert "mediaFileRowsHtml=function" not in dashboard
    assert "renderSettingsTab=async function" not in dashboard


def test_entity_cards_keep_current_add_actions_and_no_library_delete():
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    start = app.index("function entityCard")
    end = app.index("function bindEntityActions")
    card = app[start:end]

    assert "data-add-only>Add</button>" in card
    assert "data-add-monitor>Add & Monitor</button>" in card
    assert "data-add>Add & Monitor All" not in card
    assert "data-remove>Remove" not in card


def test_frontend_formats_date_only_values_without_utc_day_shift():
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    fmt = app[app.index("const fmtDate="):app.index("const bytes=")]

    assert "split('-').map(Number)" in fmt
    compact=fmt.replace(" ", "")
    assert "newDate(y,m-1,day)" in compact


def test_profiles_use_cached_local_metadata_and_paginate_scene_lists():
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    performer = app[app.index("async function performerProfile"):app.index("async function studioProfile")]
    studio = app[app.index("async function studioProfile"):app.index("async function openLocalScene")]
    scene = app[app.index("async function scenePage"):app.index("async function remoteDetail")]

    assert "loadAllPerformerScenes" in performer
    assert "loadAllStudioScenes" in studio
    assert "let x=local?localPerformerProfile(local):await api" in performer
    assert "let x=local?{...local,id:local.tpdb_id}:await api" in studio
    assert "if(!local){try{remote=await api" in scene
    assert "local?.monitored?'':" in performer.replace(" ", "")
    assert "local?.monitored?'':" in studio.replace(" ", "")


class EmptyFilteredPagePerformerTPDB:
    def __init__(self):
        self.calls: list[int] = []

    async def get_performer_scenes(self, identifier, page=1, per_page=48):
        self.calls.append(page)
        scene = RemoteScene(id=f"scene-{page}", title=f"Scene {page}", studio=RemoteStudio(id="s", name="Studio"))
        if page == 2:
            return SearchResponse(items=[], total=3 * per_page, page=page, per_page=per_page)
        if page <= 3:
            return SearchResponse(items=[scene], total=3 * per_page, page=page, per_page=per_page)
        return SearchResponse(items=[], total=3 * per_page, page=page, per_page=per_page)


@pytest.mark.asyncio
async def test_monitored_performer_scan_continues_after_filtered_empty_page():
    from scarletx.monitored_entities import _performer_scan

    tpdb = EmptyFilteredPagePerformerTPDB()
    scenes, _head, unchanged = await _performer_scan(tpdb, "performer-1", ())

    assert unchanged is False
    assert tpdb.calls[:3] == [1, 2, 3]
    assert [scene.id for scene in scenes] == ["scene-1", "scene-3"]


class FiftyOnePagePerformerTPDB:
    async def get_performer_scenes(self, identifier, page=1, per_page=48):
        total = 51 * per_page
        scene = RemoteScene(id=f"scene-{page}", title=f"Scene {page}", studio=RemoteStudio(id="s", name="Studio"))
        return SearchResponse(items=[scene], total=total, page=page, per_page=per_page)


@pytest.mark.asyncio
async def test_monitored_performer_scan_does_not_silently_truncate_after_fifty_pages():
    from scarletx.monitored_entities import _performer_scan

    scenes, _head, unchanged = await _performer_scan(FiftyOnePagePerformerTPDB(), "performer-1", ())

    assert unchanged is False
    assert len(scenes) == 51
    assert scenes[-1].id == "scene-51"


class NumericFallbackStudioTPDB:
    async def get_studio(self, identifier):
        return RemoteStudio(id=identifier, search_id=None, name="Studio")

    async def search_scenes(self, query=None, page=1, per_page=48, performer_id=None, site_id=None):
        assert site_id == "77"
        scene = RemoteScene(id="scene-1", title="Scene 1", studio=RemoteStudio(id="77", name="Studio"))
        return SearchResponse(items=[scene], total=1, page=page, per_page=per_page)


@pytest.mark.asyncio
async def test_monitored_studio_scan_uses_numeric_identifier_fallback():
    from scarletx.monitored_entities import _studio_scan

    scenes, _head, unchanged = await _studio_scan(NumericFallbackStudioTPDB(), "77", ())

    assert unchanged is False
    assert [scene.id for scene in scenes] == ["scene-1"]


def test_calendar_default_date_uses_server_local_date_not_utc_rollover():
    source = (ROOT / "scarletx" / "routes" / "application.py").read_text(encoding="utf-8")
    start = source.index("def calendar(")
    end = source.index("\n\n", start)
    function_head = source[start:end]

    assert "date.today()" in function_head
    assert "datetime.now(UTC).date()" not in function_head


def test_media_scan_caps_ffmpeg_workers_at_two():
    source = (ROOT / "scarletx" / "media_library.py").read_text(encoding="utf-8")
    assert "workers = min(2," in source


def test_playback_conversion_uses_unique_or_locked_temporary_output():
    source = (ROOT / "scarletx" / "media_library.py").read_text(encoding="utf-8")
    section = source[source.index("def ensure_browser_playback"):]
    assert "playback.tmp.mp4" not in section


def test_performer_model_persists_full_profile_metadata():
    from scarletx.models import Performer

    required = {
        "birthday",
        "deathday",
        "birthplace",
        "nationality",
        "ethnicity",
        "measurements",
        "cup_size",
        "fake_boobs",
        "waist",
        "hips",
        "height",
        "weight",
        "hair_color",
        "eye_color",
        "tattoos",
        "piercings",
        "astrology",
        "career_start_year",
        "career_end_year",
        "status",
    }
    columns = set(Performer.__table__.columns.keys())
    assert required <= columns


def test_startup_recovery_resumes_supported_background_jobs():
    source = (ROOT / "scarletx" / "routes" / "application.py").read_text(encoding="utf-8")
    lifespan = source[source.index("async def lifespan"):source.index("app = FastAPI")]

    assert "resume_background_jobs" in lifespan
    assert "Interrupted by application restart" not in lifespan
