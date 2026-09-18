from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from scarletx.db import get_session
from scarletx.models import MediaFile
from scarletx.wanted import missing_items
from tests.test_wanted_state_section23 import _factory, _scene


def test_wanted_pages_ties_without_duplicates_and_keeps_filters():
    factory = _factory()
    with factory() as db:
        scenes = [_scene(str(i), 'Same title') for i in range(125)]
        for scene in scenes:
            scene.release_date = date(2026, 1, 1)
        scenes[-1].monitored = False
        db.add_all(scenes)
        db.flush()
        db.add(MediaFile(scene_id=scenes[-2].id, path='/media/present.mp4', size_bytes=1))
        db.commit()
        statements = []
        event.listen(db.get_bind(), 'before_cursor_execute', lambda c, cu, sql, params, ctx, many: statements.append(sql))
        pages = [missing_items(db, limit=50, offset=offset) for offset in [0, 50, 100, 150]]
        assert [len(page) for page in pages] == [50, 50, 23, 0]
        ids = [row['library_item_id'] for page in pages for row in page]
        assert ids == [scene.id for scene in scenes[:123]]
        assert len(statements) == 4
        assert all('LIMIT' in sql and 'OFFSET' in sql for sql in statements)


def test_wanted_api_keeps_list_contract_and_validates_offset():
    from scarletx.routes.application import wanted_missing
    factory = _factory()
    app = FastAPI()
    app.add_api_route('/api/wanted/missing', wanted_missing, methods=['GET'])

    def session():
        with factory() as db:
            yield db

    app.dependency_overrides[get_session] = session
    with factory() as db:
        db.add_all([_scene(str(i), f'Title {i:03}') for i in range(60)])
        db.commit()
    client = TestClient(app)
    response = client.get('/api/wanted/missing?limit=50&offset=50')
    assert response.status_code == 200
    assert len(response.json()) == 10
    assert response.json()[0]['title'] == 'Title 050'
    assert client.get('/api/wanted/missing?offset=-1').status_code == 422
    assert client.get('/api/wanted/missing?limit=5001').status_code == 422
