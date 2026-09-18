from collections import Counter

from sqlalchemy import event, select, text

from scarletx.media_library import scan_library
from scarletx.models import MediaFile, MediaProbe, Scene, UnmatchedMediaFile
from scarletx.wanted import cutoff_unmet
from tests.test_incremental_scanner import _database, _add_root
from tests.test_latency_queries import populated_session


def test_partial_scan_loads_only_scoped_records_without_global_scene_index(tmp_path):
    engine, factory = _database(tmp_path)
    root = tmp_path / 'chosen%_folder'
    root.mkdir()
    _add_root(factory, root)
    with factory() as db:
        scene = Scene(tpdb_id='scene', title='Scene', content_type='scene')
        db.add(scene)
        db.flush()
        files = [MediaFile(scene_id=scene.id, path=str(root / 'missing.mp4'))]
        files += [MediaFile(scene_id=scene.id, path=str(tmp_path / 'chosenZZfolder' / f'{i}.mp4')) for i in range(200)]
        db.add_all(files)
        db.flush()
        db.add_all(MediaProbe(media_file_id=media.id, missing=False) for media in files)
        db.add_all(UnmatchedMediaFile(path=str(tmp_path / 'outside' / f'{i}.mp4'), display_name=str(i), missing=False) for i in range(200))
        db.commit()
        selected_id, outside_id = files[0].id, files[-1].id
    loaded = Counter()
    event.listen(factory, 'loaded_as_persistent', lambda session, obj: loaded.update([type(obj).__name__]))
    result = scan_library(factory, directories=[root])
    assert result['missing'] == 1
    assert loaded['MediaFile'] == 1
    assert loaded['MediaProbe'] == 1
    assert loaded['UnmatchedMediaFile'] == 0
    assert loaded['Scene'] == 0
    with factory() as db:
        assert db.get(MediaProbe, selected_id).missing
        assert not db.get(MediaProbe, outside_id).missing
        assert not db.scalar(select(UnmatchedMediaFile.missing))
    engine.dispose()


def test_scan_keeps_legacy_relative_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    engine, factory = _database(tmp_path)
    root = tmp_path / 'selected'
    root.mkdir()
    with factory() as db:
        scene = Scene(tpdb_id='relative', title='Relative', content_type='scene')
        db.add(scene)
        db.flush()
        media = MediaFile(scene_id=scene.id, path='selected/deleted.mp4')
        db.add(media)
        db.commit()
        media_id = media.id
    assert scan_library(factory, directories=[root])['missing'] == 1
    with factory() as db:
        assert db.get(MediaProbe, media_id).missing
    engine.dispose()


def test_cutoff_stops_after_bounded_batch_and_crosses_batches():
    engine, factory = populated_session(1200)
    loaded = Counter()
    event.listen(factory, 'loaded_as_persistent', lambda session, obj: loaded.update([type(obj).__name__]))
    with factory() as db:
        assert len(cutoff_unmet(db, limit=1)) == 1
    assert loaded['Scene'] <= 200
    assert loaded['MediaFile'] <= 200
    with factory() as db:
        rows = cutoff_unmet(db, limit=230)
        assert len(rows) == 230
        assert len({row['library_item_id'] for row in rows}) == 230
        assert {row['current_quality'] for row in rows} == {'720p'}
    engine.dispose()


def test_wanted_indexes_upgrade_in_place_and_are_used(tmp_path):
    from scarletx.migrations import ensure_performance_indexes, performance_index_migration_required
    engine, factory = _database(tmp_path)
    indexes = {
        'ix_history_scene_event_created': "SELECT max(created_at) FROM history WHERE scene_id=1 AND event_type IN ('scene_search','automatic_search')",
        'ix_tracked_downloads_scene_created_id': 'SELECT status FROM tracked_downloads WHERE scene_id=1 ORDER BY created_at DESC, id DESC LIMIT 1',
        'ix_scenes_wanted_order': "SELECT id FROM scenes WHERE content_type='scene' AND monitored=1 ORDER BY release_date,title,id LIMIT 51",
    }
    with factory() as db:
        db.add(Scene(tpdb_id='preserved', title='Preserved', content_type='scene'))
        db.commit()
    with engine.begin() as connection:
        for name in indexes:
            connection.exec_driver_sql(f'DROP INDEX IF EXISTS {name}')
        assert performance_index_migration_required(connection)
        ensure_performance_indexes(connection)
        ensure_performance_indexes(connection)
        for name, query in indexes.items():
            details = ' '.join(str(row[3]) for row in connection.exec_driver_sql('EXPLAIN QUERY PLAN '+query))
            assert name in details, details
            assert 'USE TEMP B-TREE' not in details
        assert connection.scalar(text("SELECT title FROM scenes WHERE tpdb_id='preserved'")) == 'Preserved'
        assert not performance_index_migration_required(connection)
    engine.dispose()


def test_cutoff_batches_preserve_best_quality_and_custom_profiles():
    from sqlalchemy import update
    from scarletx.models import LibraryItemConfig, QualityProfile
    engine, factory = populated_session(600)
    with factory() as db:
        db.execute(update(MediaFile).where(MediaFile.scene_id <= 400).values(quality='1080p'))
        profile = QualityProfile(name='720 cutoff', content_type='scene', cutoff_quality='720p', is_default=False)
        db.add(profile)
        db.flush()
        db.execute(update(LibraryItemConfig).where(LibraryItemConfig.scene_id == 401).values(quality_profile_id=profile.id))
        db.add(MediaFile(scene_id=403, path='/media/better-403.mp4', quality='2160p'))
        db.execute(update(Scene).where(Scene.id == 405).values(monitored=False))
        db.commit()
        rows = cutoff_unmet(db, limit=3)
    assert [row['library_item_id'] for row in rows] == [407, 409, 411]
    engine.dispose()


def test_empty_cutoff_does_not_create_a_profile(tmp_path):
    from scarletx.models import QualityProfile
    engine, factory = _database(tmp_path)
    with factory() as db:
        assert cutoff_unmet(db) == []
        assert db.scalar(select(QualityProfile.id)) is None
    engine.dispose()


def test_scan_retains_absolute_symlink_alias_records(tmp_path):
    engine, factory = _database(tmp_path)
    root = tmp_path / 'real'
    root.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(root, target_is_directory=True)
    with factory() as db:
        scene = Scene(tpdb_id='alias', title='Alias', content_type='scene')
        db.add(scene)
        db.flush()
        media = MediaFile(scene_id=scene.id, path=str(alias / 'deleted.mp4'))
        unmatched = UnmatchedMediaFile(path=str(alias / 'unknown.mp4'), display_name='Unknown', missing=False)
        db.add_all([media, unmatched])
        db.commit()
        media_id, unmatched_id = media.id, unmatched.id
    assert scan_library(factory, directories=[root])['missing'] == 1
    with factory() as db:
        assert db.get(MediaProbe, media_id).missing
        assert db.get(UnmatchedMediaFile, unmatched_id).missing
    engine.dispose()
