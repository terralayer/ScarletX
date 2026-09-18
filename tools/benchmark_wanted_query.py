"""Synthetic local Wanted-query benchmark and SQLite query-plan capture."""
import argparse
import json
from pathlib import Path
import tempfile
import time

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from scarletx.db import Base
from scarletx.migrations import ensure_performance_indexes
from scarletx.models import History, Scene, TrackedDownload
from scarletx.wanted import missing_items


def main(output):
    with tempfile.TemporaryDirectory() as directory:
        engine = create_engine(f'sqlite:///{directory}/wanted.db')
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            ensure_performance_indexes(conn)
        factory = sessionmaker(bind=engine)
        with factory() as db:
            db.add_all(Scene(id=i, tpdb_id=str(i), title=f'Scene {i:04}', content_type='scene', monitored=True) for i in range(1, 1001))
            db.flush()
            db.add_all(History(scene_id=i, event_type='scene_search', message='search') for i in range(1, 1001) for j in range(5))
            db.add_all(TrackedDownload(scene_id=i, nzo_id=f'{i}-{j}', release_title='release', status='failed') for i in range(1, 1001) for j in range(5))
            db.commit()
        statements = []
        def capture(conn, cursor, statement, parameters, *_):
            if statement.startswith('SELECT'):
                statements.append((statement, parameters))
        event.listen(engine, 'before_cursor_execute', capture)
        durations = []
        with factory() as db:
            for _ in range(5):
                start = time.perf_counter()
                assert len(missing_items(db, limit=51)) == 51
                durations.append((time.perf_counter() - start) * 1000)
        event.remove(engine, 'before_cursor_execute', capture)
        sql, params = statements[-1]
        with engine.connect() as conn:
            plan = [row[3] for row in conn.exec_driver_sql('EXPLAIN QUERY PLAN '+sql, params)]
        result = {'scenes':1000,'history_rows':5000,'download_rows':5000,'page_size':51,'runs_ms':[round(x,2) for x in durations],'median_ms':round(sorted(durations)[2],2),'query_plan':plan}
        output.write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
        engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    main(parser.parse_args().output)
