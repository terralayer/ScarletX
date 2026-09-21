from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def section(source: str, start: str, end: str) -> str:
    return source[source.index(start):source.index(end)]


def compact(source: str) -> str:
    return "".join(source.split())


def test_entity_library_and_search_ignore_stale_navigation_results():
    navigation = compact((FRONTEND / "navigation_error_overrides.js").read_text(encoding="utf-8"))
    search = compact((FRONTEND / "entity_search.js").read_text(encoding="utf-8"))
    library = section(navigation, "loadEntityLibrary=asyncfunction", "loadAllPerformerScenes=asyncfunction")

    guard = "if(view!==type||!entityRequestCurrent(type,generation)||$('#entityGrid')!==grid)return"
    assert library.count(guard) >= 2
    assert "constcurrent=()=>view===type&&entityRequestCurrent(type,generation)&&$('#entityGrid')===grid" in search
    assert search.count("if(!current())returnfalse") >= 2


def test_runtime_entity_library_and_search_ignore_stale_navigation_errors():
    override_path = FRONTEND / "navigation_error_overrides.js"
    assert override_path.exists(), "navigation error handling must be isolated in a runtime override"
    source = compact(override_path.read_text(encoding="utf-8"))
    search = compact((FRONTEND / "entity_search.js").read_text(encoding="utf-8"))

    assert "loadEntityLibrary=asyncfunction" in source
    assert "functionsearchEntity(type,query,options={})" in search
    guard = "if(view!==type||!entityRequestCurrent(type,generation)||$('#entityGrid')!==grid)return"
    assert source.count(guard) >= 2
    assert "catch(e){" + guard + ";notify(e.message,'error');returnfalse}" in source
    assert "catch(error){if(!current())returnfalse" in search
    assert "notify(error.message,'error');returnfalse" in search

    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    assert '<script src="/navigation_error_overrides.js"></script>' in index
    assert '<script src="/entity_search.js"></script>' in index
    assert "COPY frontend/navigation_error_overrides.js /usr/share/nginx/html/navigation_error_overrides.js" in dockerfile
    assert "COPY frontend/entity_search.js /usr/share/nginx/html/entity_search.js" in dockerfile


def test_top_level_async_pages_ignore_results_after_navigation():
    source = (FRONTEND / "app.js").read_text(encoding="utf-8")
    activity_lists = (FRONTEND / "activity_lists.js").read_text(encoding="utf-8")
    wanted = section(source, "async function wanted", "function activityPager")
    activity = section(source, "async function activity", "async function calendar")
    calendar = section(source, "async function calendar", "let settingsTab")
    settings = section(source, "async function settings", "function val")

    assert "if(view!=='wanted'||requestId!==wantedRequest||!body.isConnected)return" in wanted
    assert "initializeActivityLists()" in activity
    assert "view!=='activity'||activitySectionHost(kind)!==host||request!==state.request" in activity_lists
    assert "if(view!=='calendar')return" in calendar
    assert "if(view!=='settings')return" in settings


def test_runtime_library_ignores_results_after_navigation():
    source = (FRONTEND / "ui_overrides.js").read_text(encoding="utf-8")
    library = source[source.index("async function mediaLibrary"):]

    assert "if(view!=='library'||requestId!==mediaLibraryRequest||$('#libraryFiles')!==filesHost||$('#libraryStats')!==statsHost)return false" in library
    assert "if(view!=='library'||requestId!==mediaLibraryPageRequest||$('#libraryFiles')!==filesHost||mediaLibraryPage!==requestedPage)return false" in source
