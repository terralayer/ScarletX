from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.db import Base
from scarletx.list_queries import performer_summary_page, scene_summary_page, studio_summary_page
from scarletx.models import MediaFile, Performer, Scene, Studio


ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def _session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_performer_gender_filter_returns_only_the_selected_gender():
    db = _session()
    female = Performer(tpdb_id="female", name="Female", gender="Female", is_library=True)
    male = Performer(tpdb_id="male", name="Male", gender="Male", is_library=True)
    female_scene = Scene(tpdb_id="female-scene", title="Female Scene", content_type="scene", monitored=True)
    male_scene = Scene(tpdb_id="male-scene", title="Male Scene", content_type="scene", monitored=True)
    female_scene.performers.append(female)
    male_scene.performers.append(male)
    db.add_all([female_scene, male_scene])
    db.commit()

    page = performer_summary_page(db, limit=10, gender="female")

    assert [item["tpdb_id"] for item in page["items"]] == ["female"]
    assert page["total"] == 1


def test_performer_library_only_includes_explicitly_monitored_performers():
    db = _session()
    included = Performer(tpdb_id="included", name="Included", is_library=True, monitored=True)
    excluded = Performer(tpdb_id="excluded", name="Excluded", is_library=True, monitored=False)
    monitored_scene = Scene(tpdb_id="monitored-scene", title="Monitored", content_type="scene", monitored=True)
    unmonitored_scene = Scene(tpdb_id="unmonitored-scene", title="Unmonitored", content_type="scene", monitored=False)
    monitored_scene.performers.append(included)
    monitored_scene.performers.append(excluded)
    unmonitored_scene.performers.append(included)
    db.add_all([monitored_scene, unmonitored_scene])
    db.commit()

    page = performer_summary_page(db, limit=10, monitored_only=True)

    assert [item["tpdb_id"] for item in page["items"]] == ["included"]


def test_studio_library_only_includes_explicitly_monitored_studios():
    db = _session()
    included = Studio(tpdb_id="included-studio", name="Included Studio", is_library=True, monitored=True)
    excluded = Studio(tpdb_id="excluded-studio", name="Excluded Studio", is_library=True, monitored=False)
    monitored_scene = Scene(tpdb_id="studio-monitored", title="Monitored", content_type="scene", monitored=True, studio=included)
    monitored_scene_with_unmonitored_studio = Scene(tpdb_id="studio-monitored-unmonitored", title="Monitored", content_type="scene", monitored=True, studio=excluded)
    unmonitored_scene = Scene(tpdb_id="studio-unmonitored", title="Unmonitored", content_type="scene", monitored=False, studio=included)
    db.add_all([monitored_scene, monitored_scene_with_unmonitored_studio, unmonitored_scene])
    db.commit()

    page = studio_summary_page(db, limit=10, monitored_only=True)

    assert [item["tpdb_id"] for item in page["items"]] == ["included-studio"]


def test_scene_status_filter_distinguishes_downloaded_and_monitored_scenes():
    db = _session()
    downloaded = Scene(tpdb_id="downloaded", title="Downloaded", content_type="scene", monitored=False)
    monitored = Scene(tpdb_id="monitored", title="Monitored", content_type="scene", monitored=True)
    other = Scene(tpdb_id="other", title="Other", content_type="scene", monitored=False)
    db.add_all([downloaded, monitored, other])
    db.flush()
    db.add(MediaFile(scene_id=downloaded.id, path="/library/downloaded.mp4", size_bytes=1))
    db.commit()

    downloaded_page = scene_summary_page(db, limit=10, status="downloaded")
    monitored_page = scene_summary_page(db, limit=10, status="monitored")

    assert [item["tpdb_id"] for item in downloaded_page["items"]] == ["downloaded"]
    assert [item["tpdb_id"] for item in monitored_page["items"]] == ["monitored"]


def test_library_filter_controls_request_server_filtered_pages():
    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "entityLibraryFilter" in source
    assert "entityLibraryFilter={scenes:'monitored'" in source
    assert "monitored_only=true" in source
    assert "data-library-filter" in source
    assert "['female','Female']" in source
    assert "['male','Male']" in source
    assert "['downloaded','Downloaded']" in source
    assert "['monitored','Monitored']" in source
    assert "filterKey" in source
    assert "entityLibraryCache[type]=null" in source


def test_global_search_shows_main_page_cards_before_selecting_result_type():
    app_source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    page_source = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert 'id="globalSearchType"' not in page_source
    assert "searchChoiceQuery=q;view='search-choice';nav();render()" in app_source
    assert "function searchChoice()" in app_source
    assert 'data-search-choice="performers"' in app_source
    assert 'data-search-choice="scenes"' in app_source
    assert 'data-search-choice="studios"' in app_source
    assert 'data-icon="search-choice-performer"' in app_source
    assert 'data-icon="search-choice-scene"' in app_source
    assert 'data-icon="search-choice-studio"' in app_source
    assert "renderEntities(target,q)" in app_source


def test_entity_pages_do_not_show_the_library_add_search_mode_switch():
    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert '<button data-mode="library"' not in source
    assert 'Add / Search' not in source


def test_entity_pages_use_only_the_top_search_box():
    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'id="entitySearch"' not in source
    assert 'id="entityQ"' not in source
