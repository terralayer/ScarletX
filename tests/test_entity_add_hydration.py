from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_performer_and_studio_add_always_queue_metadata_hydration():
    source = (ROOT / "scarletx" / "routes" / "application.py").read_text()
    performer_start = source.index("async def import_performer(")
    studio_start = source.index("async def import_studio(")
    monitor_start = source.index("async def monitor_performer(")
    performer = source[performer_start:studio_start]
    studio = source[studio_start:monitor_start]

    assert "_queue_adult_entity_hydration" in performer
    assert "_queue_adult_entity_hydration" in studio
    assert "if request.monitored else None" not in performer
    assert "if request.monitored else None" not in studio


def test_hydration_fetches_full_scene_details_and_batches_cache_writes():
    path = ROOT / "scarletx" / "entity_hydration.py"
    assert path.exists(), "entity hydration service must exist"
    source = path.read_text()

    assert "await tpdb.get_scene(" in source
    assert "asyncio.Semaphore" in source
    assert 'upsert_scene(db, remote, monitored=False, content_type="scene", commit=False)' in source
    assert "db.commit()" in source
    assert "performers_cached" in source


def test_monitored_add_searches_after_hydration_without_second_tpdb_crawl():
    path = ROOT / "scarletx" / "entity_hydration.py"
    assert path.exists(), "entity hydration service must exist"
    source = path.read_text()

    assert "search_when_monitored" in source
    assert "search_and_grab_scene" in source
    assert "scene_ids" in source
