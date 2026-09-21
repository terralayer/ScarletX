"""Smoke-test locally built release images in disposable rootless containers.

Run: python tools/smoke_container_release.py --runtime podman --output results.json
This does not replace installation/upgrade testing on TrueNAS.
"""

import argparse
import http.cookiejar
import json
import subprocess
import time
import urllib.request
import uuid
import tomllib
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--runtime", choices=["podman"], default="podman")
parser.add_argument("--backend", default="localhost/scarletx:0.5.0-candidate")
parser.add_argument("--web", default="localhost/scarletx-web:0.5.0-candidate")
parser.add_argument("--upgrade-from", help="Previous local backend image; replace it using the same volumes")
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
with (Path(__file__).resolve().parents[1] / "pyproject.toml").open("rb") as handle:
    version = tomllib.load(handle)["project"]["version"]


def run(*command):
    return subprocess.check_output([args.runtime, *command], text=True).strip()


results = []
for uid, port in [(568, 18869), (1000, 18870)]:
    prefix = f"sxprep-{uid}-{uuid.uuid4().hex[:8]}"
    volumes = []
    names = []
    try:
        run("network", "create", prefix)
        mounts = []
        for folder in ["config", "downloads", "media", "backups"]:
            volume = f"{prefix}-{folder}"
            run("volume", "create", volume)
            volumes.append(volume)
            mounts += ["-v", f"{volume}:/{folder}:U" if args.runtime == "podman" else f"{volume}:/{folder}"]
        backend = prefix + "-backend"
        web = prefix + "-web"
        names = [web, backend]
        backend_command = (
            "run",
            "-d",
            "--name",
            backend,
            "--network",
            prefix,
            "--user",
            f"{uid}:{uid}",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            *mounts,
            "-e",
            "SCARLETX_DEFAULT_MEDIA_ROOT=/media",
        )
        run(*backend_command, args.upgrade_from or args.backend)
        run(
            "run",
            "-d",
            "--name",
            web,
            "--network",
            prefix,
            "--user",
            f"{uid}:{uid}",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "-e",
            f"SCARLETX_BACKEND_HOST={backend}",
            "-e",
            "SCARLETX_WEB_PORT=8080",
            "-p",
            f"127.0.0.1:{port}:8080",
            args.web,
        )
        base = f"http://127.0.0.1:{port}"

        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

        def api(path, data=None, method=None):
            request = urllib.request.Request(
                base + path,
                data=json.dumps(data).encode() if data is not None else None,
                headers={"Content-Type": "application/json", "Origin": base},
                method=method,
            )
            with opener.open(request, timeout=3) as response:
                return None if response.status == 204 else json.load(response)

        def health():
            for i in range(60):
                try:
                    result = api("/api/health")
                    if result.get("version") == version:
                        return result
                except Exception:
                    pass
                time.sleep(1)
            raise RuntimeError("Health timed out")

        health()
        assert run("exec", backend, "id", "-u") == str(uid)
        assert run("exec", web, "id", "-u") == str(uid)
        agreement = api("/api/setup/agreement")
        assert agreement["required"] and not agreement["accepted"]
        accepted = api("/api/setup/agreement", {"accepted": True, "version": agreement["current_version"]}, "POST")
        assert accepted["accepted"] and accepted["accepted_at"]
        key = api("/api/setup/api-key")["api_key"]
        password = uuid.uuid4().hex
        api("/api/setup/admin", {"username": "smoke-admin", "password": password, "password_confirm": password, "api_key": key}, "POST")
        # Anonymous clients must be denied, while integration keys work through nginx.
        try:
            urllib.request.urlopen(base + "/api/settings", timeout=3)
            raise AssertionError("Anonymous settings access succeeded")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        integration_request = urllib.request.Request(base + "/api/settings", headers={"X-Api-Key": key})
        with urllib.request.urlopen(integration_request, timeout=3) as integration_response:
            assert integration_response.status == 200
        api("/api/auth/logout", {}, "POST")
        api("/api/auth/login", {"username": "smoke-admin", "password": password}, "POST")
        settings = api("/api/settings")
        assert not settings["theporndb"]["configured"]
        assert not settings["newznab_indexers"]
        assert not settings["native_usenet"]["providers"]
        api("/api/settings/general", {"app_name": "Persistence check", "log_level": "INFO"}, "PATCH")
        run("exec", backend, "python", "-c",
            "from scarletx.db import SessionLocal; from scarletx.models import Scene,MediaFile; "
            "db=SessionLocal(); scene=Scene(tpdb_id='smoke-library',title='Smoke library'); "
            "db.add(scene); db.flush(); db.add(MediaFile(scene_id=scene.id,path='/media/smoke.mp4')); db.commit(); db.close()")
        backup = api("/api/backups", {}, "POST")
        assert backup["path"].startswith("/backups/")
        second_backup = api("/api/backups", {}, "POST")
        assert second_backup["path"] != backup["path"]
        run(
            "exec",
            backend,
            "sh",
            "-ec",
            "touch /config/write-check /downloads/write-check /media/write-check /backups/write-check; command -v par2; command -v ffprobe; command -v 7z; command -v unrar",
        )
        run(
            "exec",
            backend,
            "python",
            "-c",
            "import socket,ssl; s=socket.create_connection(('api.theporndb.net',443),timeout=10); tls=ssl.create_default_context().wrap_socket(s,server_hostname='api.theporndb.net'); tls.close()",
        )
        if args.upgrade_from:
            run("stop", backend)
            run("rm", backend)
            run(*backend_command, args.backend)
        else:
            run("restart", backend)
        health()
        assert api("/api/settings")["general"]["app_name"] == "Persistence check"
        assert api("/api/setup/agreement")["accepted"]
        with urllib.request.urlopen(integration_request, timeout=3) as response:
            assert response.status == 200
        index_names = json.loads(run("exec", backend, "python", "-c",
            "import sqlite3,json; c=sqlite3.connect('/config/scarletx.db'); "
            "print(json.dumps([r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='index'\")]))"))
        assert {"ix_history_scene_event_created", "ix_tracked_downloads_scene_created_id", "ix_scenes_wanted_order"} <= set(index_names)
        with urllib.request.urlopen(base + "/settings_ui.css") as response:
            assert b"max-width:68ch" in response.read()
        run("exec", backend, "python", "-c",
            "from scarletx.db import SessionLocal; from scarletx.models import MediaFile; "
            "from scarletx.scan_path_index import refresh_scan_path_index,scoped_records; "
            "refresh_scan_path_index(SessionLocal); db=SessionLocal(); "
            "assert len(list(scoped_records(db,MediaFile,('/media/',),refresh=False)))==1; db.close()")
        # Management endpoints and assets must survive upgrades and remain authenticated.
        for endpoint in ("storage", "backup-reminder", "cleanup", "download-schedule", "connections"):
            api("/api/operations/" + endpoint)
            try:
                urllib.request.urlopen(base + "/api/operations/" + endpoint, timeout=3)
                raise AssertionError("Anonymous management access succeeded")
            except urllib.error.HTTPError as exc:
                assert exc.code == 401
        api("/api/operations/download-schedule", {"enabled": False, "timezone": "America/Los_Angeles", "start": "21:00", "end": "06:00"}, "PATCH")
        run("restart", backend)
        health()
        assert api("/api/operations/download-schedule")["rule"]["start"] == "21:00"
        with urllib.request.urlopen(base + "/management_ui.js") as response:
            assert b"Download schedule" in response.read()
        with urllib.request.urlopen(base + "/management_ui.css") as response:
            assert b"management-storage-card" in response.read()
        # Restore only this smoke test's disposable database with the backend stopped.
        api("/api/settings/general", {"app_name": "Changed after backup", "log_level": "INFO"}, "PATCH")
        run("stop", backend)
        restore_code = (
            "import os,sqlite3,shutil; from pathlib import Path; "
            "source=Path(" + repr(backup["path"]) + "); "
            "c=sqlite3.connect(str(source)); assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; c.close(); "
            "target=Path('/config/scarletx.db'); "
            "[Path(str(target)+suffix).unlink(missing_ok=True) for suffix in ('-wal','-shm')]; "
            "shutil.copy2(source,target); "
            "shutil.copy2(source.with_suffix('.secret.key'),'/config/.scarletx-secret.key'); "
            "os.chmod('/config/.scarletx-secret.key',0o600)"
        )
        run("run", "--rm", "--user", f"{uid}:{uid}", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            *mounts, "--entrypoint", "python", args.backend, "-c", restore_code)
        run("start", backend)
        health()
        assert api("/api/settings")["general"]["app_name"] == "Persistence check"
        assert api("/api/setup/agreement")["accepted"]
        with urllib.request.urlopen(integration_request, timeout=3) as response:
            assert response.status == 200
        api("/api/auth/logout", {}, "POST")
        api("/api/auth/login", {"username": "smoke-admin", "password": password}, "POST")
        run("exec", backend, "python", "-c",
            "from scarletx.db import SessionLocal; from scarletx.models import Scene; from sqlalchemy import select; "
            "db=SessionLocal(); assert db.scalar(select(Scene.title).where(Scene.tpdb_id=='smoke-library'))=='Smoke library'; db.close()")
        results.append(
            {
                "uid": uid,
                "health": "passed",
                "configured_credentials": "disposable administrator; no external credentials",
                "writable_mounts": "all four",
                "backup": "created and restored with matching key; settings, session, API key and login verified",
                "restart_persistence": "passed",
                "upgrade_from": args.upgrade_from,
                "index_migration": "passed; canonical path cache populated after upgrade",
                "outbound_tls": "verified handshake passed",
                "web_assets": "approved UI and management assets present",
                "management": "authenticated endpoints, saved schedule and restart persistence passed",
            }
        )
        print(json.dumps(results[-1]), flush=True)
    except Exception:
        for name in names:
            subprocess.run([args.runtime, "logs", "--tail", "70", name])
        raise
    finally:
        for name in names:
            subprocess.run(
                [args.runtime, "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        for volume in volumes:
            subprocess.run(
                [args.runtime, "volume", "rm", volume], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        subprocess.run(
            [args.runtime, "network", "rm", prefix], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
args.output.write_text(json.dumps(results, indent=2))
