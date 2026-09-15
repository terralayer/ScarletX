from datetime import date
import json

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from scarletx.db import Base
from scarletx.models import Performer, Scene
from scarletx import tpdb_date_diagnostic as diagnostic


@pytest.mark.asyncio
async def test_sample_records_pages_dates_and_calendar_limit_without_writes(tmp_path):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        people = [Performer(tpdb_id=f'p{i}', name=f'Person {i}', monitored=True) for i in range(101)]
        db.add_all(people)
        db.add(Performer(tpdb_id='unmonitored', name='Excluded', monitored=False))
        db.add_all([
            Scene(tpdb_id='s1', title='A', release_date=date(2026, 9, 1), performers=people),
            Scene(tpdb_id='s2', title='B', release_date=date(2026, 9, 2), performers=people),
        ])
        db.commit()
        def respond(request):
            page = int(request.url.params['page'])
            raw = {'id': f's{page}', 'title': 'Raw title', 'date': f'2026-09-0{page}T12:00:00Z',
                   'release_date': '2026-10-01', 'site': {'id': 1, 'name': 'Studio'}}
            return httpx.Response(200, json={'data': [raw], 'meta': {'current_page': page, 'last_page': 2}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url='https://example.test') as client:
            report = await diagnostic.run_sample(db, client, tmp_path, seed=42, count=100,
                                                  start=date(2026, 9, 1), end=date(2026, 9, 30), limit=1)
        assert report['sampled_performers'] == 100
        assert report['completed_performers'] == 100
        assert len(set(report['performer_ids'])) == 100
        assert 'unmonitored' not in report['performer_ids']
        rows = [json.loads(line) for line in (tmp_path / 'scenes.jsonl').read_text().splitlines()]
        assert len(rows) == 200
        assert rows[0]['raw_date_fields']['date'] == '2026-09-01T12:00:00Z'
        assert rows[0]['normalized_date'] == rows[0]['stored_date'] == '2026-09-01'
        assert rows[0]['calendar_status'] == 'included'
        assert rows[0]['raw_identifiers'] == {'id': 's1'}
        assert rows[0]['raw_title'] == 'Raw title'
        assert rows[1]['calendar_status'] == 'limit_excluded'
        assert rows[0]['raw_date_fields']['release_date'] == '2026-10-01'
        assert not db.new and not db.dirty and not db.deleted
        assert diagnostic.select_sample(db, 100, 42) == diagnostic.select_sample(db, 100, 42)


@pytest.mark.asyncio
async def test_partial_errors_and_insufficient_population_are_explicit(tmp_path):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Performer(tpdb_id='p1', name='One', monitored=True))
        db.commit()
        with pytest.raises(ValueError, match='Only 1 monitored'):
            diagnostic.select_sample(db, 100, 42)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)),
                                     base_url='https://example.test') as client:
            report = await diagnostic.run_sample(db, client, tmp_path, seed=42, count=1,
                                                  start=date(2026, 9, 1), end=date(2026, 9, 30))
        assert report['completed_performers'] == 0
        assert report['errors'][0]['http_status'] == 503
        assert report['complete'] is False


def test_snapshot_is_read_only_and_missing_database_not_created(tmp_path):
    import sqlite3
    path = tmp_path / 'source.db'
    source = sqlite3.connect(path)
    source.execute('create table marker(value text)')
    source.execute("insert into marker values ('unchanged')")
    source.commit()
    source.close()
    before = path.read_bytes()
    engine = diagnostic.snapshot_engine(path)
    with engine.connect() as conn:
        assert conn.exec_driver_sql('select value from marker').scalar() == 'unchanged'
        with pytest.raises(Exception, match='readonly'):
            conn.exec_driver_sql("update marker set value='modified'")
    engine.dispose()
    assert path.read_bytes() == before
    missing = tmp_path / 'missing.db'
    with pytest.raises(sqlite3.OperationalError):
        diagnostic.snapshot_engine(missing)
    assert not missing.exists()


@pytest.mark.parametrize('raw_date,stored_date,status,flag', [
    (None, None, 'stored_date_missing', 'upstream_date_missing'),
    ('invalid', None, 'stored_date_missing', 'date_not_parsed'),
    ('2026-09-01', date(2026, 8, 1), 'outside_window', 'stored_normalized_mismatch'),
])
def test_date_evidence_does_not_conflate_pipeline_stages(raw_date, stored_date, status, flag):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Scene(tpdb_id='s', title='Stored', release_date=stored_date))
        db.commit()
        record = diagnostic.scene_record(db, {'id': 's', 'title': 'Raw', 'date': raw_date},
                                         set(), set(), date(2026, 9, 1), date(2026, 9, 30))
        assert record['calendar_status'] == status
        assert flag in record['flags']
        assert record['raw_date_fields']['date'] == raw_date


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [
    {'data': [], 'meta': {'current_page': 1, 'last_page': 2}},
    {'data': [None], 'meta': {'last_page': 1}},
    {'data': [], 'meta': ['invalid']},
])
async def test_bad_pages_always_produce_incomplete_summary(tmp_path, payload):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Performer(tpdb_id='p', name='Person', monitored=True))
        db.commit()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)),
                                     base_url='https://example.test') as client:
            report = await diagnostic.run_sample(db, client, tmp_path, seed=42, count=1,
                                                  start=date(2026, 9, 1), end=date(2026, 9, 30))
        assert report['complete'] is False
        assert report['completed_performers'] == 0
        assert len(report['errors']) == 1
        assert (tmp_path / 'summary.json').exists()


def test_snapshot_can_resolve_tpdb_credentials_from_database(tmp_path, monkeypatch):
    from scarletx.models import AppSetting
    from scarletx.secret_store import encrypt_secret

    key_file = tmp_path / 'secret.key'
    monkeypatch.setenv('SCARLETX_SECRET_KEY_FILE', str(key_file))
    path = tmp_path / 'credentials.db'
    source_engine = create_engine(f'sqlite:///{path}')
    Base.metadata.create_all(source_engine)
    with Session(source_engine) as db:
        db.add_all([
            AppSetting(key='theporndb_api_key', value=encrypt_secret('database-key'), is_secret=True),
            AppSetting(key='theporndb_base_url', value='https://tpdb.example', is_secret=False),
        ])
        db.commit()
    source_engine.dispose()

    engine = diagnostic.snapshot_engine(path)
    try:
        with Session(engine) as db:
            resolver = getattr(diagnostic, 'resolve_tpdb_credentials', None)
            assert callable(resolver)
            assert resolver(db) == ('database-key', 'https://tpdb.example')
    finally:
        engine.dispose()
