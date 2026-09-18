"""Exercise production pagination/search/Wanted paths against a disposable large library."""

import argparse
import json
import tempfile
import time
import tracemalloc
from pathlib import Path

from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from scarletx.db import Base
from scarletx.models import Scene, MediaFile, History, QualityProfile
from scarletx.routes.application import _scene_summary_rows
from scarletx.wanted import missing_items, cutoff_unmet


def main(count, output):
    with tempfile.TemporaryDirectory(prefix="scarletx-large-") as directory:
        engine = create_engine(f"sqlite:///{directory}/library.db")
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            for start in range(1, count + 1, 500):
                ids = range(start, min(start + 500, count + 1))
                conn.execute(
                    insert(Scene),
                    [
                        dict(
                            id=i,
                            tpdb_id=str(i),
                            title=f"{'Needle' if i % 1000 == 0 else 'Scene'} {i:06}",
                            description="Fixture metadata. " * 100,
                            content_type="scene",
                            monitored=True,
                        )
                        for i in ids
                    ],
                )
                conn.execute(
                    insert(History),
                    [dict(scene_id=i, event_type="scene_search", message="Fixture search") for i in ids],
                )
                files = [dict(scene_id=i, path=f"/media/{i}.mp4", quality="720p") for i in ids if i % 2 == 0]
                if files:
                    conn.execute(insert(MediaFile), files)
            conn.exec_driver_sql("CREATE VIRTUAL TABLE scene_search USING fts5(title)")
            conn.exec_driver_sql("INSERT INTO scene_search(rowid,title) SELECT id,title FROM scenes")
        with Session(engine) as db:
            db.add(
                QualityProfile(
                    name="Fixture 1080", content_type="scene", cutoff_quality="1080p", is_default=True
                )
            )
            db.commit()
        tracemalloc.start()
        durations = []
        total = 0
        cursor = None
        seen = set()
        started = time.perf_counter()
        with Session(engine) as db:
            while True:
                tick = time.perf_counter()
                page = _scene_summary_rows(db, limit=100, cursor=cursor)
                durations.append((time.perf_counter() - tick) * 1000)
                ids = [item["id"] for item in page["items"]]
                assert not seen.intersection(ids), "Duplicate pagination results"
                seen.update(ids)
                total += len(ids)
                assert len(db.identity_map) <= 101, "Unbounded ORM retention"
                if not page["has_more"]:
                    break
                cursor = page["next_cursor"]
            assert total == count
            search = _scene_summary_rows(db, limit=100, q="Needle")
            assert search["total"] == count // 1000
            first = missing_items(db, limit=51)
            deep = missing_items(db, limit=51, offset=1000)
            assert len(first) == len(deep) == 51
            assert len(cutoff_unmet(db, limit=51)) == 51
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        result = dict(
            scenes=count,
            media_files=count // 2,
            history=count,
            pages=len(durations),
            visited=total,
            page_median_ms=round(sorted(durations)[len(durations) // 2], 2),
            page_max_ms=round(max(durations), 2),
            elapsed_seconds=round(time.perf_counter() - started, 2),
            traced_peak_mb=round(peak / 1024 / 1024, 2),
            checks="complete cursor traversal without duplicates, bounded ORM retention, FTS search, first/deep Wanted pages, cutoff",
        )
        output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenes", type=int, default=50000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.scenes < 5000:
        parser.error("--scenes must be at least 5000")
    main(args.scenes, args.output)
