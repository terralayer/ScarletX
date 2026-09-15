from __future__ import annotations

from collections import namedtuple

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_disk_capacity_accounts_for_required_bytes_and_reserve(tmp_path, monkeypatch):
    from scarletx import resource_guard

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(resource_guard.shutil, "disk_usage", lambda _path: usage(20_000, 14_000, 6_000))

    enough = resource_guard.check_disk_capacity(
        tmp_path,
        required_bytes=2_000,
        reserve_bytes=3_000,
    )
    assert enough.allowed is True
    assert enough.available_after_required == 4_000

    blocked = resource_guard.check_disk_capacity(
        tmp_path,
        required_bytes=4_000,
        reserve_bytes=3_000,
    )
    assert blocked.allowed is False
    assert blocked.reason == "free_space_reserve"


def test_low_disk_keeps_queued_job_runnable_instead_of_failing(tmp_path, monkeypatch):
    from scarletx.db import Base
    from scarletx.models import NativeUsenetJob
    from scarletx.usenet.scheduler import _resource_ready_for_job

    engine = create_engine(f"sqlite:///{tmp_path / 'backpressure.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(
            NativeUsenetJob(
                id="queued-low-disk",
                title="Queued",
                nzb_url="https://example.invalid/queued.nzb",
                status="queued",
                total_bytes=8_000,
                downloaded_bytes=1_000,
            )
        )
        db.commit()

    class Settings:
        native_usenet_incomplete_dir = str(tmp_path)
        minimum_free_space_gb = 1.0

    monkeypatch.setattr(
        "scarletx.usenet.scheduler.check_disk_capacity",
        lambda *_args, **_kwargs: type("Decision", (), {"allowed": False})(),
    )

    assert _resource_ready_for_job(factory, Settings(), "queued-low-disk") is False
    with factory() as db:
        assert db.get(NativeUsenetJob, "queued-low-disk").status == "queued"


def test_zero_or_unknown_size_still_enforces_reserve(tmp_path, monkeypatch):
    from scarletx.db import Base
    from scarletx.models import NativeUsenetJob
    from scarletx.usenet.scheduler import _resource_ready_for_job

    engine = create_engine(f"sqlite:///{tmp_path / 'unknown-size.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(
            NativeUsenetJob(
                id="unknown-size",
                title="Unknown",
                nzb_url="https://example.invalid/unknown.nzb",
                status="queued",
                total_bytes=0,
                downloaded_bytes=0,
            )
        )
        db.commit()

    captured = {}

    class Settings:
        native_usenet_incomplete_dir = str(tmp_path)
        minimum_free_space_gb = 2.0

    def fake_check(_path, *, required_bytes, reserve_bytes):
        captured["required_bytes"] = required_bytes
        captured["reserve_bytes"] = reserve_bytes
        return type("Decision", (), {"allowed": True})()

    monkeypatch.setattr("scarletx.usenet.scheduler.check_disk_capacity", fake_check)
    assert _resource_ready_for_job(factory, Settings(), "unknown-size") is True
    assert captured["required_bytes"] == 0
    assert captured["reserve_bytes"] == 2 * 1024**3
