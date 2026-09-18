"""Repeatable local ASGI auth benchmark; optional simulated SQLite read latency."""
import argparse
import asyncio
import json
from pathlib import Path
import tempfile
import time

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from scarletx.auth import create_session
from scarletx.db import Base
from scarletx.http_security import install_authentication
from scarletx.models import AuthUser
from scarletx.settings_store import load_database_settings


async def measure(delay_ms, count=160, concurrency=8):
    with tempfile.TemporaryDirectory() as directory:
        engine = create_engine(f'sqlite:///{directory}/bench.db', connect_args={'check_same_thread': False})
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as db:
            db.add(AuthUser(id=1, username='bench', username_normalized='bench', password_hash='unused'))
            db.commit()
            token = create_session(db, 1)
            load_database_settings(db)
        queries = 0
        settings_loads = 0

        @event.listens_for(engine, 'before_cursor_execute')
        def record_query(*_):
            nonlocal queries
            queries += 1
            if delay_ms:
                time.sleep(delay_ms / 1000)

        def settings_loader(db, **kwargs):
            nonlocal settings_loads
            settings_loads += 1
            return load_database_settings(db, **kwargs)

        app = FastAPI()

        @app.get('/api/private')
        async def private():
            return {'ok': True}

        install_authentication(app, session_factory=factory, settings_loader=settings_loader)
        durations, lags = [], []
        done = False

        async def heartbeat():
            while not done:
                start = time.perf_counter()
                await asyncio.sleep(.002)
                lags.append(max(0, time.perf_counter() - start - .002) * 1000)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://bench', cookies={'scarletx_session': token}) as client:
            semaphore = asyncio.Semaphore(concurrency)

            async def request():
                async with semaphore:
                    start = time.perf_counter()
                    response = await client.get('/api/private')
                    response.raise_for_status()
                    durations.append((time.perf_counter() - start) * 1000)

            monitor = asyncio.create_task(heartbeat())
            start = time.perf_counter()
            await asyncio.gather(*(request() for _ in range(count)))
            elapsed = time.perf_counter() - start
            done = True
            await monitor
        engine.dispose()
        return {'requests': count, 'concurrency': concurrency, 'simulated_query_delay_ms': delay_ms,
                'elapsed_seconds': round(elapsed, 3), 'requests_per_second': round(count / elapsed, 1),
                'request_p95_ms': round(sorted(durations)[int(len(durations)*.95)-1], 2),
                'max_event_loop_delay_ms': round(max(lags), 2), 'sql_queries': queries, 'settings_loads': settings_loads}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = [await measure(delay) for delay in [0, 5]]
    args.output.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
