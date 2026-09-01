from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import queue
import socket
import ssl
import struct
import subprocess
import threading
import time
import uuid
import zipfile
from tempfile import TemporaryDirectory
import zlib
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal
from xml.etree import ElementTree

import httpx
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select, update

try:
    import sabctools  # SIMD yEnc + cross-platform positional file writer
except Exception:  # The pure-Python/C-stdlib path remains a safe fallback.
    sabctools = None

from .archive_security import parse_7z_listing, validate_archive_member_path, validate_extracted_tree
from .status_console import emit_status
from .models import History, NativeUsenetJob, TrackedDownload, utcnow


class NativeUsenetError(RuntimeError):
    pass


class UsenetProviderConfig(BaseModel):
    name: str
    host: str
    port: int = Field(default=563, ge=1, le=65535)
    username: str = ""
    password: SecretStr = SecretStr("")
    use_ssl: Literal[True] = True
    connections: int = Field(default=8, ge=1, le=150)
    enabled: bool = True
    priority: int = Field(default=25, ge=1, le=50)


@dataclass(frozen=True)
class NZBSegment:
    number: int
    bytes: int
    message_id: str
    age_days: float | None = None


@dataclass(frozen=True)
class NZBFile:
    subject: str
    groups: tuple[str, ...]
    segments: tuple[NZBSegment, ...]


@dataclass(frozen=True)
class DecodedSegment:
    path: Path
    size: int
    filename: str | None
    provider: str | None = None
    begin: int | None = None
    total_size: int | None = None


class NNTPConnection:
    """Small TLS-only NNTP client focused on authenticated BODY retrieval."""

    def __init__(self, provider: UsenetProviderConfig, timeout: float = 30.0):
        self.provider = provider
        self.timeout = timeout
        self.sock: socket.socket | ssl.SSLSocket | None = None
        self.file = None

    def connect(self) -> None:
        self.close()
        raw = socket.create_connection((self.provider.host, self.provider.port), timeout=self.timeout)
        raw.settimeout(self.timeout)
        try:
            raw.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
            raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            raw.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            pass
        # ScarletX native NNTP is TLS-only by policy. There is deliberately no
        # plaintext socket fallback.
        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        self.sock = ctx.wrap_socket(raw, server_hostname=self.provider.host)
        self.file = self.sock.makefile("rb", buffering=1024 * 1024)
        greeting = self._readline().decode("utf-8", "replace")
        if not greeting.startswith(("200", "201")):
            raise NativeUsenetError(f"{self.provider.name}: NNTP rejected connection: {greeting}")
        if self.provider.username:
            user = self._command(f"AUTHINFO USER {self.provider.username}")
            if user.startswith("381"):
                password = self.provider.password.get_secret_value()
                if not password:
                    raise NativeUsenetError(f"{self.provider.name}: password is required")
                reply = self._command(f"AUTHINFO PASS {password}")
                if not reply.startswith(("281", "250")):
                    raise NativeUsenetError(f"{self.provider.name}: authentication failed")
            elif not user.startswith(("281", "250")):
                raise NativeUsenetError(f"{self.provider.name}: authentication failed")

    def abort(self) -> None:
        """Immediately tear down a socket so a blocked BODY read wakes on cancel."""
        sock, fileobj = self.sock, self.file
        self.sock = None
        self.file = None
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass
        try:
            if fileobj:
                fileobj.close()
        except Exception:
            pass

    def close(self) -> None:
        try:
            if self.sock:
                try:
                    self.sock.sendall(b"QUIT\r\n")
                except Exception:
                    pass
        finally:
            self.abort()

    def _readline(self) -> bytes:
        if self.file is None:
            raise NativeUsenetError("NNTP connection is not open")
        line = self.file.readline()
        if not line:
            raise NativeUsenetError(f"{self.provider.name}: NNTP connection closed")
        return line.rstrip(b"\r\n")

    def _command(self, command: str) -> str:
        if self.sock is None:
            raise NativeUsenetError("NNTP connection is not open")
        self.sock.sendall(command.encode("utf-8") + b"\r\n")
        return self._readline().decode("utf-8", "replace")

    def body_iter(self, message_id: str):
        """Yield one NNTP BODY line at a time so large articles are never buffered whole."""
        if self.sock is None:
            self.connect()
        ident = message_id.strip()
        if not ident.startswith("<"):
            ident = f"<{ident}>"
        reply = self._command(f"BODY {ident}")
        if reply.startswith(("430", "423")):
            raise FileNotFoundError(f"{self.provider.name}: article unavailable")
        if not reply.startswith("222"):
            if reply == ".":
                raise NativeUsenetError(f"{self.provider.name}: NNTP stream desynchronized before BODY response")
            raise NativeUsenetError(f"{self.provider.name}: BODY failed: {reply}")
        while True:
            line = self._readline()
            if line == b".":
                break
            if line.startswith(b".."):
                line = line[1:]
            yield line

    def body_wire_iter(self, message_id: str, chunk_size: int = 512 * 1024):
        """Yield a complete BODY response using large buffered wire chunks.

        SABCTools understands NNTP framing/dot-stuffing itself. Reading the article
        in large blocks avoids one Python ``readline`` call for every encoded yEnc
        line while still consuming the final dot terminator before the connection is
        returned to the persistent pool.
        """
        if self.sock is None:
            self.connect()
        ident = message_id.strip()
        if not ident.startswith("<"):
            ident = f"<{ident}>"
        reply = self._command(f"BODY {ident}")
        if reply.startswith(("430", "423")):
            raise FileNotFoundError(f"{self.provider.name}: article unavailable")
        if not reply.startswith("222"):
            if reply == ".":
                raise NativeUsenetError(f"{self.provider.name}: NNTP stream desynchronized before BODY response")
            raise NativeUsenetError(f"{self.provider.name}: BODY failed: {reply}")
        yield reply.encode("utf-8", "replace") + b"\r\n"

        if self.file is None:
            raise NativeUsenetError("NNTP connection is not open")
        read_block = getattr(self.file, "read1", self.file.read)
        pending = b""
        body_start = True
        while True:
            chunk = read_block(max(8192, int(chunk_size)))
            if not chunk:
                raise NativeUsenetError(f"{self.provider.name}: NNTP connection closed during BODY")
            data = pending + chunk

            # An empty article is simply '.\r\n'. Otherwise the unique NNTP
            # multiline terminator is '\r\n.\r\n'; data lines beginning with
            # a dot are wire-escaped as '..', so this marker cannot occur as payload.
            end = 3 if body_start and data.startswith(b".\r\n") else -1
            if end < 0:
                marker = data.find(b"\r\n.\r\n")
                if marker >= 0:
                    end = marker + 5
            if end >= 0:
                yield data[:end]
                # NNTP is request/response and ScarletX does not pipeline commands,
                # so the server cannot legitimately send bytes beyond this BODY
                # response before the next command.
                return

            # Retain only enough bytes to catch a terminator split across reads.
            if len(data) > 4:
                yield data[:-4]
                pending = data[-4:]
                body_start = False
            else:
                pending = data

    def body(self, message_id: str) -> list[bytes]:
        # Compatibility helper used by tests/tools. The downloader itself streams.
        return list(self.body_iter(message_id))


def test_provider(provider: UsenetProviderConfig) -> dict:
    connection = NNTPConnection(provider)
    started = time.monotonic()
    emit_status(provider.name, "CONNECTING", f"TLS :{provider.port}", severity="active")
    try:
        connection.connect()
        latency_ms = round((time.monotonic() - started) * 1000)
        emit_status(provider.name, "CONNECTED", f"TLS :{provider.port} | {latency_ms} ms", severity="ok")
        return {
            "ok": True,
            "provider": provider.name,
            "host": provider.host,
            "port": provider.port,
            "ssl": provider.use_ssl,
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        emit_status(provider.name, "FAILED", exc.__class__.__name__, severity="error")
        raise
    finally:
        connection.close()


def parse_nzb(payload: bytes) -> list[NZBFile]:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise NativeUsenetError(f"Invalid NZB XML: {exc}") from exc

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    files: list[NZBFile] = []
    for file_el in root.iter():
        if local(file_el.tag) != "file":
            continue
        subject = file_el.attrib.get("subject", "download")
        groups: list[str] = []
        segments: list[NZBSegment] = []
        try:
            posted_epoch = int(file_el.attrib.get("date", "0") or 0)
            age_days = max(0.0, (time.time() - posted_epoch) / 86400.0) if posted_epoch > 0 else None
        except (TypeError, ValueError):
            age_days = None
        for child in file_el:
            if local(child.tag) == "groups":
                groups.extend((g.text or "").strip() for g in child if local(g.tag) == "group" and (g.text or "").strip())
            elif local(child.tag) == "segments":
                for seg in child:
                    if local(seg.tag) != "segment" or not (seg.text or "").strip():
                        continue
                    try:
                        number = int(seg.attrib.get("number", "0"))
                        size = int(seg.attrib.get("bytes", "0"))
                    except ValueError:
                        continue
                    segments.append(NZBSegment(number=number, bytes=max(0, size), message_id=(seg.text or "").strip(), age_days=age_days))
        if segments:
            segments.sort(key=lambda item: item.number)
            files.append(NZBFile(subject=subject, groups=tuple(groups), segments=tuple(segments)))
    if not files:
        raise NativeUsenetError("NZB contains no downloadable files")
    return files


def _parse_yenc_value(line: bytes, key: bytes) -> str | None:
    marker = key + b"="
    pos = line.find(marker)
    if pos < 0:
        return None
    value = line[pos + len(marker):]
    if key == b"name":
        return value.decode("utf-8", "replace").strip()
    return value.split(None, 1)[0].decode("ascii", "replace").strip()


_YENC_TRANSLATION = bytes.maketrans(
    bytes(range(256)),
    bytes(((value - 42) & 0xFF) for value in range(256)),
)
_YENC_ESCAPE = re.compile(rb"=(.)", re.S)


def _decode_yenc_line(line: bytes) -> bytes:
    # yEnc escapes only a small fraction of bytes. Resolve those escapes in C-backed
    # regex code, then apply the -42 transform to the whole line with bytes.translate.
    # This avoids the old Python byte-by-byte hot loop at high NNTP connection counts.
    if b"=" in line:
        line = _YENC_ESCAPE.sub(lambda m: bytes((((m.group(1)[0] - 64) & 0xFF),)), line)
    return line.translate(_YENC_TRANSLATION)


def decode_yenc(lines: Iterable[bytes]) -> tuple[bytes, str | None]:
    rows = list(lines)
    start = next((i for i, line in enumerate(rows) if line.startswith(b"=ybegin")), None)
    if start is None:
        # Some providers/indexers carry small plain-text attachments. Preserve them.
        return b"\n".join(rows), None
    filename = _parse_yenc_value(rows[start], b"name")
    data = bytearray()
    expected_crc: str | None = None
    for line in rows[start + 1:]:
        if line.startswith(b"=ypart"):
            continue
        if line.startswith(b"=yend"):
            expected_crc = _parse_yenc_value(line, b"pcrc32") or _parse_yenc_value(line, b"crc32")
            break
        data.extend(_decode_yenc_line(line))
    if expected_crc and re.fullmatch(r"[0-9a-fA-F]{8}", expected_crc):
        actual = f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"
        if actual.casefold() != expected_crc.casefold():
            raise NativeUsenetError(f"yEnc CRC mismatch: expected {expected_crc}, got {actual}")
    return bytes(data), filename




def decode_yenc_to_file(lines: Iterable[bytes], path: Path) -> tuple[int, str | None]:
    """Stream a yEnc article directly to disk while validating CRC."""
    iterator = iter(lines)
    prefix: list[bytes] = []
    begin: bytes | None = None
    for line in iterator:
        if line.startswith(b"=ybegin"):
            begin = line
            break
        prefix.append(line)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".part")
    if begin is None:
        payload = b"\n".join(prefix)
        temp.write_bytes(payload)
        temp.replace(path)
        return len(payload), None

    filename = _parse_yenc_value(begin, b"name")
    expected_crc: str | None = None
    crc = 0
    size = 0
    try:
        with temp.open("wb", buffering=1024 * 1024) as output:
            yenc_complete = False
            for line in iterator:
                # The NNTP multiline response does not end at =yend; it ends at a
                # separate dot line consumed by NNTPConnection.body_iter(). Keep
                # draining the iterator after =yend so pooled connections remain
                # protocol-aligned for the next BODY command.
                if yenc_complete:
                    continue
                if line.startswith(b"=ypart"):
                    continue
                if line.startswith(b"=yend"):
                    expected_crc = _parse_yenc_value(line, b"pcrc32") or _parse_yenc_value(line, b"crc32")
                    yenc_complete = True
                    continue
                decoded = _decode_yenc_line(line)
                output.write(decoded)
                crc = zlib.crc32(decoded, crc)
                size += len(decoded)
        if expected_crc and re.fullmatch(r"[0-9a-fA-F]{8}", expected_crc):
            actual = f"{crc & 0xFFFFFFFF:08x}"
            if actual.casefold() != expected_crc.casefold():
                raise NativeUsenetError(f"yEnc CRC mismatch: expected {expected_crc}, got {actual}")
        temp.replace(path)
        return size, filename
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _parse_yenc_int(line: bytes, key: bytes) -> int | None:
    value = _parse_yenc_value(line, key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _write_all_fd(fd: int, offset: int, data: bytes) -> None:
    view = memoryview(data)
    written = 0
    if hasattr(os, "pwrite"):
        while written < len(view):
            n = os.pwrite(fd, view[written:], offset + written)
            if n <= 0:
                raise OSError("short positional write")
            written += n
        return
    os.lseek(fd, offset, os.SEEK_SET)
    while written < len(view):
        n = os.write(fd, view[written:])
        if n <= 0:
            raise OSError("short file write")
        written += n


def decode_yenc_to_target(
    lines: Iterable[bytes],
    path: Path,
    *,
    write_lock: threading.Lock | None = None,
) -> tuple[int, str | None, int | None, int | None]:
    """Fallback decoder: stream one yEnc article directly into its final offset."""
    iterator = iter(lines)
    prefix: list[bytes] = []
    begin_line: bytes | None = None
    for line in iterator:
        if line.startswith(b"=ybegin"):
            begin_line = line
            break
        prefix.append(line)

    path.parent.mkdir(parents=True, exist_ok=True)
    if begin_line is None:
        payload = b"\n".join(prefix)
        fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            if write_lock is None:
                _write_all_fd(fd, 0, payload)
            else:
                with write_lock:
                    _write_all_fd(fd, 0, payload)
        finally:
            os.close(fd)
        return len(payload), None, 1, len(payload)

    filename = _parse_yenc_value(begin_line, b"name")
    total_size = _parse_yenc_int(begin_line, b"size")
    part_begin = 1
    expected_crc: str | None = None
    crc = 0
    decoded_size = 0
    offset = 0
    yenc_complete = False

    fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        if total_size and total_size > 0:
            current = os.fstat(fd).st_size
            if current != total_size:
                os.ftruncate(fd, total_size)

        for line in iterator:
            if yenc_complete:
                # Drain through the NNTP terminator so pooled connections stay aligned.
                continue
            if line.startswith(b"=ypart"):
                part_begin = _parse_yenc_int(line, b"begin") or 1
                offset = max(0, part_begin - 1)
                continue
            if line.startswith(b"=yend"):
                expected_crc = _parse_yenc_value(line, b"pcrc32") or _parse_yenc_value(line, b"crc32")
                yenc_complete = True
                continue
            decoded = _decode_yenc_line(line)
            if write_lock is None or hasattr(os, "pwrite"):
                _write_all_fd(fd, offset + decoded_size, decoded)
            else:
                with write_lock:
                    _write_all_fd(fd, offset + decoded_size, decoded)
            crc = zlib.crc32(decoded, crc)
            decoded_size += len(decoded)
    finally:
        os.close(fd)

    if expected_crc and re.fullmatch(r"[0-9a-fA-F]{8}", expected_crc):
        actual = f"{crc & 0xFFFFFFFF:08x}"
        if actual.casefold() != expected_crc.casefold():
            raise NativeUsenetError(f"yEnc CRC mismatch: expected {expected_crc}, got {actual}")
    return decoded_size, filename, part_begin, total_size


def decode_yenc_native(connection: NNTPConnection, segment: NZBSegment, writer) -> tuple[int, str | None, int | None, int | None]:
    """Decode and write a BODY response with SABCTools' SIMD decoder when available."""
    if sabctools is None:
        raise NativeUsenetError("SABCTools is not available")
    decoder = sabctools.Decoder(1024 * 1024)
    decoder.expect(segment.message_id, writer)
    responses = []
    for chunk in connection.body_wire_iter(segment.message_id):
        view = memoryview(chunk)
        position = 0
        while position < len(view):
            target = memoryview(decoder)
            count = min(len(target), len(view) - position)
            target[:count] = view[position:position + count]
            target.release()
            decoder.process(count)
            position += count
            responses.extend(decoder)
    responses.extend(decoder)
    response = next((r for r in responses if getattr(r, "context", None) == segment.message_id), None)
    if response is None:
        raise NativeUsenetError("SABCTools did not produce a BODY response")
    if getattr(response, "sink_failed", False):
        error = getattr(response, "sink_error", None)
        raise NativeUsenetError(f"SABCTools file sink failed: {error or 'unknown error'}")
    if getattr(response, "crc", None) is None:
        raise NativeUsenetError("yEnc CRC mismatch")
    size = int(getattr(response, "bytes_decoded", 0) or 0)
    filename = getattr(response, "file_name", None)
    if isinstance(filename, bytes):
        filename = filename.decode("utf-8", "replace")
    begin_zero = getattr(response, "part_begin", None)
    begin = (int(begin_zero) + 1) if begin_zero is not None else None
    total_size = getattr(response, "file_size", None)
    return size, filename, begin, int(total_size) if total_size else None


def _read_done_marker(path: Path) -> int:
    try:
        raw = path.read_text(errors="ignore").strip().split("|", 1)[0]
        return max(0, int(raw))
    except Exception:
        return 0


def _write_done_marker(path: Path, size: int, begin: int | None, total_size: int | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(f"{int(size)}|{int(begin or 0)}|{int(total_size or 0)}")
    temp.replace(path)


def _file_download_priority(item: NZBFile, index: int) -> tuple[int, bool]:
    """Return scheduling priority and whether this is a deferred PAR2 recovery volume."""
    subject = item.subject.casefold()
    guessed = _subject_filename(item.subject, index).casefold()
    text = f"{subject} {guessed}"
    is_par2 = ".par2" in text or " par2" in text
    recovery_volume = is_par2 and bool(re.search(r"(?:\.vol\d+[-+]\d+|vol\d+)", text, re.I))
    if recovery_volume:
        return 90, True
    if any(ext in text for ext in (".mp4", ".mkv", ".m4v", ".avi", ".mov", ".wmv", ".webm")):
        return 0, False
    if any(token in text for token in (".part01.rar", ".part001.rar", ".rar", ".r00", ".7z", ".zip")):
        return 10, False
    if is_par2:
        return 20, False
    if any(ext in text for ext in (".nfo", ".sfv", ".jpg", ".jpeg", ".png")):
        return 70, False
    return 30, False

def _safe_filename(value: str, fallback: str) -> str:
    name = Path(value or fallback).name.strip().replace("\x00", "")
    name = re.sub(r"[\\/:*?\"<>|]", "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:240] or fallback


def _subject_filename(subject: str, index: int) -> str:
    # Prefer quoted filenames from common NZB subject formats.
    quoted = re.findall(r'"([^"\\/]+\.[A-Za-z0-9]{2,8})"', subject)
    if quoted:
        return _safe_filename(quoted[-1], f"file-{index:04d}.bin")
    candidates = re.findall(r"([^\s\\/]+\.(?:rar|r\d{2,3}|par2|nfo|sfv|mkv|mp4|avi|mov|wmv|zip|7z))", subject, re.I)
    if candidates:
        return _safe_filename(candidates[-1], f"file-{index:04d}.bin")
    return f"file-{index:04d}.bin"


_PAR2_MAGIC = b"PAR2\x00PKT"
_PAR2_FILEDESC = b"PAR 2.0\x00FileDesc"
_VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".ts", ".m2ts", ".mpg", ".mpeg"}


def _looks_obfuscated_name(path: Path) -> bool:
    name = path.name
    return bool(
        re.fullmatch(r"[0-9a-fA-F]{24,96}", name)
        or re.fullmatch(r"[0-9a-fA-F]{24,96}\.bin", name, re.I)
        or re.fullmatch(r"file-\d{4}\.bin", name, re.I)
        or (not path.suffix and len(name) >= 20)
    )


def _signature_extension(path: Path) -> str | None:
    """Identify common Usenet payloads without trusting an obfuscated filename."""
    try:
        with path.open("rb") as handle:
            head = handle.read(64 * 1024)
    except OSError:
        return None
    if head.startswith(_PAR2_MAGIC):
        return ".par2"
    if head.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")):
        return ".rar"
    if head.startswith(b"7z\xbc\xaf\x27\x1c"):
        return ".7z"
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return ".zip"
    if head.startswith(b"\x1aE\xdf\xa3"):
        return ".mkv"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return ".mp4"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return ".avi"
    if head.startswith(b"0&\xb2u\x8ef\xcf\x11\xa6\xd9\x00\xaa\x00b\xcel"):
        return ".wmv"
    if head.startswith(b"FLV"):
        return ".flv"
    if head.startswith(b"\x00\x00\x01\xba"):
        return ".mpg"
    if len(head) >= 377 and head[0] == 0x47 and head[188] == 0x47 and head[376] == 0x47:
        return ".ts"
    return None


def _ffprobe_video_extension(path: Path) -> str | None:
    """Fallback container detection for playable files with uncommon headers."""
    tool = shutil.which("ffprobe")
    if not tool:
        return None
    try:
        result = subprocess.run(
            [tool, "-v", "error", "-show_entries", "format=format_name", "-of", "default=nw=1:nk=1", str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=12,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    names = {x.strip().casefold() for x in (result.stdout or "").split(",") if x.strip()}
    if names & {"matroska", "webm"}:
        return ".mkv"
    if names & {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}:
        return ".mp4"
    if "avi" in names:
        return ".avi"
    if names & {"asf", "wmv"}:
        return ".wmv"
    if "mpegts" in names:
        return ".ts"
    if names & {"mpeg", "mpegvideo"}:
        return ".mpg"
    return None


def _par2_descriptions(par2_path: Path) -> list[dict]:
    """Read PAR2 FileDesc packets without loading giant recovery volumes into RAM."""
    try:
        # FileDesc packets live near the front of normal PAR2 sets.  Recovery volume
        # payloads can be hundreds of MB, so cap metadata inspection at 32 MiB.
        with par2_path.open("rb") as handle:
            payload = handle.read(32 * 1024 * 1024)
    except OSError:
        return []
    rows: list[dict] = []
    offset = 0
    total = len(payload)
    while offset + 64 <= total:
        start = payload.find(_PAR2_MAGIC, offset)
        if start < 0 or start + 64 > total:
            break
        try:
            packet_len = struct.unpack_from("<Q", payload, start + 8)[0]
        except struct.error:
            break
        if packet_len < 64:
            offset = start + 8
            continue
        # A packet can extend beyond our metadata read cap. FileDesc packets are
        # small; skip oversized packets rather than reading a recovery volume.
        if start + packet_len > total:
            break
        packet_type = payload[start + 48:start + 64]
        if packet_type == _PAR2_FILEDESC and packet_len >= 120:
            body = payload[start + 64:start + packet_len]
            if len(body) >= 56:
                raw_name = body[56:].rstrip(b"\x00")
                name = raw_name.decode("utf-8", "replace").strip()
                if name:
                    rows.append({
                        "name": _safe_filename(name, "recovered.bin"),
                        "size": int(struct.unpack_from("<Q", body, 48)[0]),
                        "md5": body[16:32],
                        "md5_16k": body[32:48],
                    })
        offset = start + int(packet_len)
    return rows


def _primary_par2_file(payload_dir: Path) -> Path | None:
    par_files = [p for p in payload_dir.rglob("*.par2") if p.is_file()]
    if not par_files:
        return None
    base = [p for p in par_files if ".vol" not in p.name.casefold()]
    candidates = base or par_files
    return min(candidates, key=lambda p: p.stat().st_size)

def _md5_first16k(path: Path) -> bytes:
    with path.open("rb") as handle:
        return hashlib.md5(handle.read(16 * 1024)).digest()


def _md5_file(path: Path) -> bytes:
    digest = hashlib.md5()
    with path.open("rb", buffering=1024 * 1024) as handle:
        while block := handle.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.digest()


def _unique_file_path(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(2, 10000):
        candidate = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise NativeUsenetError(f"Could not allocate a unique payload filename for {path.name}")


def normalize_obfuscated_payload(payload_dir: Path) -> list[str]:
    """Restore usable names/extensions for hash-named Usenet payloads quickly."""
    notes: list[str] = []

    # First expose hidden PAR2 packets. Without this, repair is never invoked.
    files = [p for p in payload_dir.rglob("*") if p.is_file()]
    for item in files:
        if _looks_obfuscated_name(item) and _signature_extension(item) == ".par2":
            target = _unique_file_path(item.with_name(item.name + ".par2"))
            old = item.name
            item.rename(target)
            notes.append(f"Detected obfuscated PAR2 {old}")

    # The small base PAR2 contains the FileDesc metadata we need. Do not parse every
    # .vol*.par2 recovery volume; those can be huge and made post-processing crawl.
    primary_par = _primary_par2_file(payload_dir)
    descriptions = _par2_descriptions(primary_par) if primary_par else []
    if descriptions:
        by_key: dict[tuple[int, bytes], list[dict]] = {}
        for desc in descriptions:
            by_key.setdefault((desc["size"], desc["md5_16k"]), []).append(desc)
        for item in [p for p in payload_dir.rglob("*") if p.is_file() and p.suffix.casefold() != ".par2"]:
            if not _looks_obfuscated_name(item):
                continue
            try:
                key = (item.stat().st_size, _md5_first16k(item))
            except OSError:
                continue
            matches = by_key.get(key, [])
            if len(matches) > 1:
                full = _md5_file(item)
                matches = [match for match in matches if match["md5"] == full]
            if not matches:
                continue
            target = _unique_file_path(item.with_name(matches[0]["name"]))
            old = item.name
            item.rename(target)
            notes.append(f"Recovered {old} -> {target.name}")

    # Signature sniffing is cheap. Avoid running ffprobe serially against every
    # unknown support/recovery file; a bounded fallback below probes only the largest.
    for item in [p for p in payload_dir.rglob("*") if p.is_file()]:
        if not _looks_obfuscated_name(item):
            continue
        ext = _signature_extension(item)
        if not ext or item.suffix.casefold() == ext:
            continue
        target = _unique_file_path(item.with_name(item.name + ext))
        old = item.name
        item.rename(target)
        notes.append(f"Identified {old} as {ext.lstrip('.').upper()}")
    return notes


def recover_unknown_videos(payload_dir: Path, max_candidates: int = 4) -> list[str]:
    """Use ffprobe only on a few large unresolved payloads as a last resort."""
    candidates = []
    for item in payload_dir.rglob("*"):
        if not item.is_file() or not _looks_obfuscated_name(item):
            continue
        try:
            size = item.stat().st_size
        except OSError:
            continue
        if size >= 8 * 1024 * 1024:
            candidates.append((size, item))
    notes: list[str] = []
    for _, item in sorted(candidates, reverse=True)[:max_candidates]:
        ext = _ffprobe_video_extension(item)
        if not ext:
            continue
        target = _unique_file_path(item.with_name(item.name + ext))
        old = item.name
        item.rename(target)
        notes.append(f"Probed {old} as {ext.lstrip('.').upper()}")
    return notes

def _playable_videos(payload_dir: Path) -> list[Path]:
    rows = [p for p in payload_dir.rglob("*") if p.is_file() and p.suffix.casefold() in _VIDEO_EXTENSIONS]
    non_samples = [p for p in rows if not re.search(r"(?:^|[. _-])(sample|trailer)(?:[. _-]|$)", p.name, re.I)]
    return sorted(non_samples or rows, key=lambda p: p.stat().st_size, reverse=True)


class _ProviderConnectionPool:
    """Bounded shared pool of persistent NNTP connections for one provider.

    Connections belong to the provider pool rather than worker threads. This both
    improves TLS connection reuse and guarantees ScarletX never leaves more open
    NNTP sessions than the provider's configured connection maximum.
    """

    def __init__(self, provider: UsenetProviderConfig):
        self.provider = provider
        self.limit = max(1, provider.connections)
        self.idle: queue.LifoQueue[NNTPConnection] = queue.LifoQueue(maxsize=self.limit)
        self.lock = threading.Lock()
        self.created = 0
        self.closed = False
        self.leased: set[NNTPConnection] = set()

    def try_acquire(self) -> NNTPConnection | None:
        """Lease immediately or return None if every session is busy."""
        if self.closed:
            raise NativeUsenetError(f"{self.provider.name}: connection pool is closed")
        try:
            connection = self.idle.get_nowait()
            with self.lock:
                self.leased.add(connection)
            return connection
        except queue.Empty:
            pass
        with self.lock:
            if self.created >= self.limit:
                return None
            self.created += 1
        try:
            connection = NNTPConnection(self.provider)
        except Exception:
            # A failed TLS/auth/connect attempt must not permanently consume one of
            # this provider's connection slots; otherwise the pool can appear full
            # forever and silently throttle/freeze later retries.
            with self.lock:
                self.created = max(0, self.created - 1)
            raise
        with self.lock:
            if self.closed:
                self.created = max(0, self.created - 1)
                connection.abort()
                raise NativeUsenetError(f"{self.provider.name}: connection pool is closed")
            self.leased.add(connection)
        return connection

    def acquire(self) -> NNTPConnection:
        while True:
            connection = self.try_acquire()
            if connection is not None:
                return connection
            time.sleep(0.01)

    def release(self, connection: NNTPConnection, *, broken: bool = False) -> None:
        with self.lock:
            self.leased.discard(connection)
        if broken or self.closed:
            try:
                connection.close()
            finally:
                with self.lock:
                    self.created = max(0, self.created - 1)
            return
        try:
            self.idle.put_nowait(connection)
        except queue.Full:
            connection.close()
            with self.lock:
                self.created = max(0, self.created - 1)

    def utilization(self) -> float:
        with self.lock:
            return min(1.0, len(self.leased) / max(1, self.limit))

    def abort_active(self) -> None:
        # Do not close the pool itself: cancellation should tear down only the live
        # BODY sockets. Worker finally blocks release them as broken and future jobs
        # can immediately create fresh sessions in this persistent pool.
        with self.lock:
            active = list(self.leased)
        for connection in active:
            try:
                connection.abort()
            except Exception:
                pass

    def close(self) -> None:
        self.closed = True
        with self.lock:
            active = list(self.leased)
            self.leased.clear()
        for connection in active:
            connection.abort()
        while True:
            try:
                connection = self.idle.get_nowait()
            except queue.Empty:
                break
            connection.abort()
        with self.lock:
            self.created = 0


_ACTIVE_FETCHERS_LOCK = threading.RLock()
_ACTIVE_FETCHERS: dict[str, "SegmentFetcher"] = {}
_SHARED_FETCHER_LOCK = threading.RLock()
_SHARED_FETCHER: "SegmentFetcher | None" = None
_SHARED_FETCHER_KEY: tuple | None = None


def _provider_pool_key(providers: list[UsenetProviderConfig], max_retries: int) -> tuple:
    return tuple(
        (p.name, p.host, p.port, p.username, p.password.get_secret_value(), p.connections, p.priority, p.enabled)
        for p in providers
    ) + (("retries", int(max_retries)),)


def _shared_segment_fetcher(providers: list[UsenetProviderConfig], max_retries: int) -> "SegmentFetcher":
    global _SHARED_FETCHER, _SHARED_FETCHER_KEY
    key = _provider_pool_key(providers, max_retries)
    with _SHARED_FETCHER_LOCK:
        if _SHARED_FETCHER is not None and _SHARED_FETCHER_KEY == key:
            return _SHARED_FETCHER
        old = _SHARED_FETCHER
        _SHARED_FETCHER = SegmentFetcher(providers, max_retries)
        _SHARED_FETCHER_KEY = key
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        return _SHARED_FETCHER


def request_cancel(job_id: str) -> bool:
    """Abort live NNTP sockets and any active post-processing tool immediately."""
    cancelled = False
    with _CANCELLED_JOBS_LOCK:
        _CANCELLED_JOBS.add(job_id)
    with _ACTIVE_FETCHERS_LOCK:
        fetcher = _ACTIVE_FETCHERS.get(job_id)
    if fetcher is not None:
        fetcher.abort_active()
        cancelled = True
    with _ACTIVE_TOOLS_LOCK:
        proc = _ACTIVE_TOOLS.get(job_id)
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
            cancelled = True
        except Exception:
            pass
    return cancelled


class SegmentFetcher:
    def __init__(self, providers: list[UsenetProviderConfig], max_retries: int):
        self.providers = sorted([p for p in providers if p.enabled], key=lambda p: p.priority)
        self.max_retries = max(0, max_retries)
        self.pools = {p.name: _ProviderConnectionPool(p) for p in self.providers}
        self.schedule_lock = threading.Lock()
        self.schedule_index = 0
        self.stats_lock = threading.Lock()
        self.target_locks_lock = threading.Lock()
        self.target_locks: dict[str, threading.Lock] = {}
        self.writer_lock = threading.Lock()
        self.writers: dict[str, object] = {}
        self.native_acceleration = sabctools is not None
        self.native_acceleration_error: str | None = None
        self.perf = {
            p.name: {
                "samples": 0,
                "bytes": 0,
                "seconds": 0.0,
                "ewma_bps": 0.0,
                "failures": 0,
                "missing": 0,
            }
            for p in self.providers
        }
        # Provider behavior often changes with article retention age. Keep separate
        # learned speed/availability statistics so an older scene can favor a server
        # that is slower for fresh posts but materially more complete for old ones.
        self.age_perf = {
            p.name: {bucket: {"samples": 0, "ewma_bps": 0.0, "failures": 0, "missing": 0}
                     for bucket in ("fresh", "year", "three_year", "archive", "unknown")}
            for p in self.providers
        }

    @staticmethod
    def _age_bucket(segment: NZBSegment) -> str:
        age = segment.age_days
        if age is None:
            return "unknown"
        if age < 30:
            return "fresh"
        if age < 365:
            return "year"
        if age < 1095:
            return "three_year"
        return "archive"

    def _provider_order(self, segment: NZBSegment) -> list[UsenetProviderConfig]:
        if not self.providers:
            return []
        with self.schedule_lock, self.stats_lock:
            unsampled = [p for p in self.providers if self.perf[p.name]["samples"] < 2]
            if unsampled:
                primary = unsampled[self.schedule_index % len(unsampled)]
                self.schedule_index += 1
            else:
                bucket = self._age_bucket(segment)
                def score(provider: UsenetProviderConfig) -> float:
                    perf = self.perf[provider.name]
                    aged = self.age_perf[provider.name][bucket]
                    use_aged = aged["samples"] >= 2
                    throughput = max(1.0, float((aged if use_aged else perf)["ewma_bps"] or 0.0))
                    failures = aged["failures"] if use_aged else perf["failures"]
                    missing = aged["missing"] if use_aged else perf["missing"]
                    reliability = 1.0 / (1.0 + failures * 0.35 + missing * 0.22)
                    availability = max(0.10, 1.0 - self.pools[provider.name].utilization() * 0.90)
                    priority_bias = 1.0 / (1.0 + max(0, provider.priority - 1) * 0.01)
                    return throughput * reliability * availability * priority_bias
                primary = max(self.providers, key=score)
            rest = sorted(
                (p for p in self.providers if p.name != primary.name),
                key=lambda p: (-(self.perf[p.name]["ewma_bps"] or 0.0), p.priority),
            )
            return [primary, *rest]

    def _record_success(self, provider: UsenetProviderConfig, size: int, seconds: float, segment: NZBSegment | None = None) -> None:
        rate = float(size) / max(0.001, seconds)
        with self.stats_lock:
            perf = self.perf[provider.name]
            perf["samples"] += 1
            perf["bytes"] += int(size)
            perf["seconds"] += float(seconds)
            prior = float(perf["ewma_bps"] or 0.0)
            perf["ewma_bps"] = rate if prior <= 0 else prior * 0.72 + rate * 0.28
            if segment is not None:
                aged = self.age_perf[provider.name][self._age_bucket(segment)]
                aged["samples"] += 1
                prior_age = float(aged["ewma_bps"] or 0.0)
                aged["ewma_bps"] = rate if prior_age <= 0 else prior_age * 0.70 + rate * 0.30

    def _record_failure(self, provider: UsenetProviderConfig, *, missing: bool = False, segment: NZBSegment | None = None) -> None:
        key = "missing" if missing else "failures"
        with self.stats_lock:
            self.perf[provider.name][key] += 1
            if segment is not None:
                self.age_perf[provider.name][self._age_bucket(segment)][key] += 1

    def best_provider(self) -> str | None:
        with self.stats_lock:
            sampled = [(float(v["ewma_bps"] or 0.0), name) for name, v in self.perf.items() if v["samples"]]
        return max(sampled)[1] if sampled else (self.providers[0].name if self.providers else None)

    def provider_stats(self) -> list[dict]:
        with self.stats_lock:
            return [
                {
                    "name": p.name,
                    "samples": int(self.perf[p.name]["samples"]),
                    "speed_bps": round(float(self.perf[p.name]["ewma_bps"] or 0.0), 2),
                    "failures": int(self.perf[p.name]["failures"]),
                    "missing": int(self.perf[p.name]["missing"]),
                    "connections": p.connections,
                }
                for p in self.providers
            ]

    def abort_active(self) -> None:
        for pool in self.pools.values():
            try:
                pool.abort_active()
            except Exception:
                pass

    def _target_lock(self, path: Path) -> threading.Lock:
        key = str(path)
        with self.target_locks_lock:
            return self.target_locks.setdefault(key, threading.Lock())

    def _target_writer(self, path: Path):
        if sabctools is None or not self.native_acceleration:
            return None
        key = str(path)
        with self.writer_lock:
            writer = self.writers.get(key)
            if writer is None:
                path.parent.mkdir(parents=True, exist_ok=True)
                writer = sabctools.FileWriter(str(path))
                self.writers[key] = writer
            return writer

    def close_target(self, path: Path) -> None:
        key = str(path)
        with self.writer_lock:
            writer = self.writers.pop(key, None)
        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass
        with self.target_locks_lock:
            self.target_locks.pop(key, None)

    def close_targets_under(self, root: Path) -> None:
        prefix = str(root)
        with self.writer_lock:
            keys = [k for k in self.writers if k.startswith(prefix)]
        for key in keys:
            self.close_target(Path(key))

    def close(self) -> None:
        with self.writer_lock:
            targets = list(self.writers)
        for target in targets:
            self.close_target(Path(target))
        for pool in self.pools.values():
            try:
                pool.close()
            except Exception:
                pass

    def fetch(self, segment: NZBSegment, path: Path) -> DecodedSegment:
        if path.exists() and path.stat().st_size > 0:
            return DecodedSegment(path=path, size=path.stat().st_size, filename=None, provider=None)
        errors: list[str] = []
        unavailable: set[str] = set()
        attempted_once: set[str] = set()
        # Retries are a total extra-attempt budget for the article, not retries per
        # provider. With two servers and max_retries=2 this is at most four attempts,
        # not six repeated failures.
        attempt_budget = max(1, len(self.providers) + self.max_retries)
        attempts = 0
        while attempts < attempt_budget:
            order = [p for p in self._provider_order(segment) if p.name not in unavailable]
            if not order:
                break
            candidates = [p for p in order if p.name not in attempted_once] or order
            provider = None
            connection = None
            for candidate in candidates:
                leased = self.pools[candidate.name].try_acquire()
                if leased is not None:
                    provider, connection = candidate, leased
                    break
            if provider is None or connection is None:
                time.sleep(0.01)
                continue
            attempted_once.add(provider.name)
            attempts += 1
            pool = self.pools[provider.name]
            broken = False
            started = time.monotonic()
            try:
                size, filename = decode_yenc_to_file(connection.body_iter(segment.message_id), path)
                self._record_success(provider, size, time.monotonic() - started, segment)
                return DecodedSegment(path=path, size=size, filename=filename, provider=provider.name)
            except FileNotFoundError as exc:
                self._record_failure(provider, missing=True, segment=segment)
                errors.append(str(exc))
                unavailable.add(provider.name)
            except Exception as exc:
                self._record_failure(provider, segment=segment)
                errors.append(f"{provider.name} attempt {attempts}: {exc}")
                broken = True
            finally:
                pool.release(connection, broken=broken)
            if attempts >= len(self.providers) and attempts < attempt_budget:
                retry_no = attempts - len(self.providers) + 1
                time.sleep(min(2.0, 0.15 * (2 ** max(0, retry_no - 1))))
        raise NativeUsenetError("; ".join(errors[-8:]) or "Article download failed")

    def fetch_into(self, segment: NZBSegment, target: Path, done_marker: Path) -> DecodedSegment:
        done_size = _read_done_marker(done_marker)
        if done_size > 0 and target.exists():
            return DecodedSegment(path=target, size=done_size, filename=None, provider=None)
        errors: list[str] = []
        unavailable: set[str] = set()
        attempted_once: set[str] = set()
        attempt_budget = max(1, len(self.providers) + self.max_retries)
        attempts = 0
        while attempts < attempt_budget:
            order = [p for p in self._provider_order(segment) if p.name not in unavailable]
            if not order:
                break
            candidates = [p for p in order if p.name not in attempted_once] or order
            provider = None
            connection = None
            for candidate in candidates:
                leased = self.pools[candidate.name].try_acquire()
                if leased is not None:
                    provider, connection = candidate, leased
                    break
            if provider is None or connection is None:
                time.sleep(0.004)
                continue
            attempted_once.add(provider.name)
            attempts += 1
            pool = self.pools[provider.name]
            broken = False
            started = time.monotonic()
            try:
                if sabctools is not None and self.native_acceleration:
                    try:
                        size, filename, begin, total_size = decode_yenc_native(
                            connection, segment, self._target_writer(target)
                        )
                    except (AttributeError, TypeError, BufferError, NotImplementedError) as native_exc:
                        # A SABCTools API/platform mismatch must never take the downloader
                        # down. Disable acceleration for this process and retry the article
                        # on a fresh connection with ScarletX's verified fallback decoder.
                        self.native_acceleration = False
                        self.native_acceleration_error = str(native_exc)[:500]
                        self.close_target(target)
                        broken = True
                        raise NativeUsenetError(
                            f"SIMD yEnc acceleration unavailable at runtime; retrying with built-in decoder: {native_exc}"
                        ) from native_exc
                else:
                    size, filename, begin, total_size = decode_yenc_to_target(
                        connection.body_iter(segment.message_id), target,
                        write_lock=self._target_lock(target),
                    )
                _write_done_marker(done_marker, size, begin, total_size)
                self._record_success(provider, size, time.monotonic() - started, segment)
                return DecodedSegment(
                    path=target, size=size, filename=filename, provider=provider.name,
                    begin=begin, total_size=total_size,
                )
            except FileNotFoundError as exc:
                self._record_failure(provider, missing=True, segment=segment)
                errors.append(str(exc))
                unavailable.add(provider.name)
            except Exception as exc:
                self._record_failure(provider, segment=segment)
                errors.append(f"{provider.name} attempt {attempts}: {exc}")
                broken = True
            finally:
                pool.release(connection, broken=broken)
            if attempts >= len(self.providers) and attempts < attempt_budget:
                retry_no = attempts - len(self.providers) + 1
                time.sleep(min(1.0, 0.08 * (2 ** max(0, retry_no - 1))))
        raise NativeUsenetError("; ".join(errors[-8:]) or "Article download failed")

def _tool_status() -> dict:
    return {
        "par2": shutil.which("par2") or shutil.which("par2repair") or shutil.which("par2verify"),
        "unrar": shutil.which("unrar") or shutil.which("unrar-free") or shutil.which("unar"),
        "7z": shutil.which("7z") or shutil.which("7zz"),
        "sabctools": bool(sabctools),
    }


def tool_status() -> dict:
    tools = _tool_status()
    return {key: bool(value) for key, value in tools.items()}


_ACTIVE_TOOLS_LOCK = threading.RLock()
_ACTIVE_TOOLS: dict[str, subprocess.Popen] = {}
_CANCELLED_JOBS_LOCK = threading.RLock()
_CANCELLED_JOBS: set[str] = set()


def _postprocess_cancelled(job_id: str | None) -> bool:
    if not job_id:
        return False
    with _CANCELLED_JOBS_LOCK:
        return job_id in _CANCELLED_JOBS


def _run_tool(command: list[str], cwd: Path, timeout: int, *, job_id: str | None = None, label: str = "Post-processing tool") -> subprocess.CompletedProcess:
    if _postprocess_cancelled(job_id):
        raise asyncio.CancelledError
    proc = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if job_id:
        with _ACTIVE_TOOLS_LOCK:
            _ACTIVE_TOOLS[job_id] = proc
    try:
        try:
            stdout, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, _ = proc.communicate()
            raise NativeUsenetError(f"{label} timed out after {timeout // 60} minutes")
        if _postprocess_cancelled(job_id):
            raise asyncio.CancelledError
        return subprocess.CompletedProcess(command, proc.returncode, stdout, None)
    finally:
        if job_id:
            with _ACTIVE_TOOLS_LOCK:
                if _ACTIVE_TOOLS.get(job_id) is proc:
                    _ACTIVE_TOOLS.pop(job_id, None)


def repair_payload(payload_dir: Path, enabled: bool, *, job_id: str | None = None) -> list[str]:
    notes: list[str] = []
    par_files = sorted(payload_dir.rglob("*.par2"))
    if not par_files:
        return notes
    if not enabled:
        notes.append("PAR2 files present; repair disabled")
        return notes
    tools = _tool_status()
    tool = tools["par2"]
    if not tool:
        notes.append("PAR2 files present; par2 tool is not installed")
        return notes
    primary = _primary_par2_file(payload_dir) or par_files[0]
    base = Path(tool).name.casefold()
    if "verify" in base:
        verify_cmd = [tool, str(primary)]
        repair_tool = shutil.which("par2repair")
        repair_cmd = [repair_tool, str(primary)] if repair_tool else None
    elif "repair" in base:
        verify_tool = shutil.which("par2verify")
        verify_cmd = [verify_tool, str(primary)] if verify_tool else [tool, str(primary)]
        repair_cmd = [tool, str(primary)]
    else:
        verify_cmd = [tool, "v", str(primary)]
        repair_cmd = [tool, "r", str(primary)]
    verified = _run_tool(verify_cmd, payload_dir, 180, job_id=job_id, label="PAR2 verification")
    if verified.returncode == 0:
        notes.append("PAR2 verification passed")
        return notes
    if not repair_cmd:
        raise NativeUsenetError("PAR2 verification failed and no repair command is available")
    repaired = _run_tool(repair_cmd, payload_dir, 600, job_id=job_id, label="PAR2 repair")
    if repaired.returncode != 0:
        tail = (repaired.stdout or verified.stdout or "PAR2 repair failed")[-1200:]
        raise NativeUsenetError(f"PAR2 repair failed: {tail}")
    notes.append("PAR2 repair completed")
    return notes


def _main_rars(payload_dir: Path) -> list[Path]:
    rars = sorted(payload_dir.rglob("*.rar"))
    result = []
    for item in rars:
        name = item.name.casefold()
        if re.search(r"\.part\d+\.rar$", name) and not re.search(r"\.part0*1\.rar$", name):
            continue
        result.append(item)
    return result


def _archive_files(payload_dir: Path) -> list[Path]:
    return [*sorted(payload_dir.rglob("*.zip")), *_main_rars(payload_dir), *sorted(payload_dir.rglob("*.7z"))]


def unpack_payload(payload_dir: Path, enabled: bool, password: str = "", *, job_id: str | None = None) -> list[str]:
    notes: list[str] = []
    if not enabled:
        return notes
    for archive in sorted(payload_dir.rglob("*.zip")):
        if _postprocess_cancelled(job_id):
            raise asyncio.CancelledError
        try:
            deadline = time.monotonic() + 600
            root = archive.parent.resolve()
            with zipfile.ZipFile(archive) as zf:
                for member in zf.infolist():
                    if _postprocess_cancelled(job_id):
                        raise asyncio.CancelledError
                    if time.monotonic() > deadline:
                        raise NativeUsenetError(f"Extracting {archive.name} timed out after 10 minutes")
                    try:
                        safe_member = validate_archive_member_path(member.filename)
                    except ValueError as exc:
                        raise NativeUsenetError(f"Unsafe path in ZIP archive {archive.name}") from exc
                    target = (archive.parent / Path(*safe_member.parts)).resolve()
                    try:
                        target.relative_to(root)
                    except ValueError as exc:
                        raise NativeUsenetError(f"Unsafe path in ZIP archive {archive.name}") from exc
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member, pwd=password.encode() if password else None) as source, target.open("wb") as output:
                        while block := source.read(4 * 1024 * 1024):
                            if _postprocess_cancelled(job_id):
                                raise asyncio.CancelledError
                            if time.monotonic() > deadline:
                                raise NativeUsenetError(f"Extracting {archive.name} timed out after 10 minutes")
                            output.write(block)
            notes.append(f"Extracted {archive.name}")
        except zipfile.BadZipFile as exc:
            raise NativeUsenetError(f"Could not unpack {archive.name}: {exc}") from exc
        except RuntimeError as exc:
            raise NativeUsenetError(f"Could not unpack {archive.name}: {exc}") from exc
    rars = _main_rars(payload_dir)
    sevens = sorted(payload_dir.rglob("*.7z"))
    if not rars and not sevens:
        return notes
    tools = _tool_status()
    archive_tool = tools["7z"]
    if not archive_tool:
        raise NativeUsenetError("Secure RAR/7z extraction requires 7z")
    for archive in [*rars, *sevens]:
        if _postprocess_cancelled(job_id):
            raise asyncio.CancelledError
        listing = [archive_tool, "l", "-slt"]
        if password:
            listing.append(f"-p{password}")
        listing.append(str(archive))
        listed = _run_tool(listing, archive.parent, 120, job_id=job_id, label=f"Listing {archive.name}")
        if listed.returncode != 0:
            raise NativeUsenetError(f"Could not inspect {archive.name}: {(listed.stdout or '')[-1200:]}")
        try:
            members = parse_7z_listing(listed.stdout or "")
        except ValueError as exc:
            raise NativeUsenetError(f"Unsafe path in archive {archive.name}: {exc}") from exc
        if not members:
            raise NativeUsenetError(f"Archive {archive.name} contains no safely listable members")
        with TemporaryDirectory(prefix=".scarletx-extract-", dir=archive.parent) as temp_dir:
            quarantine = Path(temp_dir)
            command = [archive_tool, "x", "-y"]
            if password:
                command.append(f"-p{password}")
            command.extend([f"-o{quarantine}", str(archive)])
            result = _run_tool(command, archive.parent, 600, job_id=job_id, label=f"Extracting {archive.name}")
            if result.returncode != 0:
                raise NativeUsenetError(f"Could not unpack {archive.name}: {(result.stdout or '')[-1200:]}")
            try:
                validate_extracted_tree(quarantine)
            except ValueError as exc:
                raise NativeUsenetError(f"Unsafe extracted content in {archive.name}: {exc}") from exc
            for child in quarantine.iterdir():
                target = archive.parent / child.name
                target = _unique_directory(target) if child.is_dir() else _unique_file_path(target)
                shutil.move(str(child), str(target))
        notes.append(f"Extracted {archive.name}")
    return notes


def postprocess_payload(
    payload_dir: Path,
    *,
    repair_enabled: bool,
    unpack_enabled: bool,
    password: str = "",
    job_id: str | None = None,
    stage=None,
) -> tuple[list[str], list[Path]]:
    """Bounded, short-circuiting post-processing for native Usenet payloads."""
    notes: list[str] = []

    def mark(message: str) -> None:
        if _postprocess_cancelled(job_id):
            raise asyncio.CancelledError
        if stage:
            stage(message)

    mark("Detecting downloaded payloads")
    notes.extend(normalize_obfuscated_payload(payload_dir))
    videos = _playable_videos(payload_dir)
    if not videos:
        mark("Identifying primary media")
        notes.extend(recover_unknown_videos(payload_dir))
        videos = _playable_videos(payload_dir)

    archives = _archive_files(payload_dir)
    par_present = _primary_par2_file(payload_dir) is not None

    # Direct-video posts are already complete once all yEnc segments have decoded.
    # Running PAR2 over a healthy multi-GB video adds minutes of disk I/O for no gain.
    if videos and (not archives or videos[0].stat().st_size >= 32 * 1024 * 1024):
        if par_present and repair_enabled:
            notes.append("Playable scene detected; skipped unnecessary PAR2 verification")
        if archives and unpack_enabled:
            notes.append("Playable scene detected; skipped unnecessary archive extraction")
        return notes, videos

    if par_present:
        mark("Checking PAR2 integrity")
        notes.extend(repair_payload(payload_dir, repair_enabled, job_id=job_id))
        notes.extend(normalize_obfuscated_payload(payload_dir))
        if not _playable_videos(payload_dir):
            notes.extend(recover_unknown_videos(payload_dir))
        videos = _playable_videos(payload_dir)

    archives = _archive_files(payload_dir)
    if archives and not videos:
        mark("Extracting archives")
        notes.extend(unpack_payload(payload_dir, unpack_enabled, password, job_id=job_id))
        mark("Identifying extracted media")
        notes.extend(normalize_obfuscated_payload(payload_dir))
        if not _playable_videos(payload_dir):
            notes.extend(recover_unknown_videos(payload_dir))
        videos = _playable_videos(payload_dir)

    return notes, videos

def _unique_directory(base: Path) -> Path:
    if not base.exists():
        return base
    for i in range(2, 10000):
        candidate = base.with_name(f"{base.name} ({i})")
        if not candidate.exists():
            return candidate
    raise NativeUsenetError("Could not allocate a unique completed-download directory")


_LIVE_PROGRESS_LOCK = threading.RLock()
_LIVE_PROGRESS: dict[str, dict[str, float | int | None]] = {}


def _set_live_progress(job_id: str, **values) -> None:
    with _LIVE_PROGRESS_LOCK:
        state = _LIVE_PROGRESS.setdefault(job_id, {})
        state.update(values)


def _get_live_progress(job_id: str) -> dict:
    with _LIVE_PROGRESS_LOCK:
        return dict(_LIVE_PROGRESS.get(job_id, {}))


def _clear_live_progress(job_id: str) -> None:
    with _LIVE_PROGRESS_LOCK:
        _LIVE_PROGRESS.pop(job_id, None)


def enqueue_url(session_factory, settings, url: str, title: str) -> str:
    if not native_client_ready(settings):
        raise NativeUsenetError("ScarletX built-in Usenet has no enabled provider configured")
    with session_factory() as db:
        existing = db.scalar(select(NativeUsenetJob).where(
            NativeUsenetJob.nzb_url == url,
            NativeUsenetJob.status.in_(["queued", "downloading", "paused", "postprocessing"]),
        ).order_by(NativeUsenetJob.created_at.desc()).limit(1))
        if existing:
            return existing.id
        job_id = "sx-" + uuid.uuid4().hex
        db.add(NativeUsenetJob(id=job_id, title=title, nzb_url=url, status="queued"))
        db.commit()
    return job_id



async def reprocess_completed_job(session_factory, settings, job_id: str) -> dict:
    """Re-run de-obfuscation/repair/unpack on an already downloaded payload.

    This is intentionally download-free so older preview jobs that landed in the
    completed directory as hash-named payloads can be repaired in place.
    """
    with session_factory() as db:
        job = db.get(NativeUsenetJob, job_id)
        if job is None:
            raise NativeUsenetError("Built-in download job not found")
        output_path = Path(job.output_path).expanduser().resolve() if job.output_path else None
        password = job.unpack_password or ""
    if output_path is None or not output_path.exists() or not output_path.is_dir():
        raise NativeUsenetError("Completed payload directory is missing")
    with _CANCELLED_JOBS_LOCK:
        _CANCELLED_JOBS.discard(job_id)
    def stage(message: str) -> None:
        _set_job(session_factory, job_id, postprocess_note=message)
    notes, videos = await asyncio.to_thread(
        postprocess_payload,
        output_path,
        repair_enabled=settings.native_usenet_repair_enabled,
        unpack_enabled=settings.native_usenet_unpack_enabled,
        password=password,
        job_id=job_id,
        stage=stage,
    )
    if not videos:
        names = ", ".join(p.name for p in sorted(output_path.rglob("*")) if p.is_file())[:1200]
        raise NativeUsenetError(
            "No playable scene was found after reprocessing" + (f": {names}" if names else "")
        )
    primary = videos[0]
    notes.append(f"Primary scene: {primary.name} ({primary.stat().st_size} bytes)")
    _set_job(
        session_factory, job_id, status="completed", error=None,
        postprocess_note="; ".join(notes)[:2000] if notes else f"Primary scene: {primary.name}",
        completed_at=utcnow(),
        unpack_password=None,
    )
    with session_factory() as db:
        refreshed = db.get(NativeUsenetJob, job_id)
        return job_dict(refreshed)

def native_client_ready(settings) -> bool:
    return bool(settings.native_usenet_enabled and [p for p in settings.native_usenet_providers() if p.enabled and p.host])


def _job_control(session_factory, job_id: str) -> str:
    with session_factory() as db:
        job = db.get(NativeUsenetJob, job_id)
        if job is None:
            return "missing"
        if job.cancel_requested:
            return "cancel"
        return job.status


async def _wait_if_paused(session_factory, job_id: str) -> None:
    while True:
        state = _job_control(session_factory, job_id)
        if state == "cancel":
            raise asyncio.CancelledError
        if state != "paused":
            return
        await asyncio.sleep(0.5)


def _set_job(session_factory, job_id: str, **values) -> None:
    # Lifecycle changes are persisted immediately. High-frequency transfer progress
    # uses the in-memory path below and is flushed at most once per second.
    live_values = {k: v for k, v in values.items() if k in {"total_bytes", "downloaded_bytes", "speed_bps", "eta_seconds"}}
    if live_values:
        _set_live_progress(job_id, **live_values)
    values["updated_at"] = utcnow()
    with session_factory() as db:
        db.execute(update(NativeUsenetJob).where(NativeUsenetJob.id == job_id).values(**values))
        db.commit()


def _publish_progress(session_factory, job_id: str, *, total_bytes: int, downloaded_bytes: int, speed_bps: float, eta_seconds: int | None, persist: bool) -> None:
    values = {
        "total_bytes": int(total_bytes),
        "downloaded_bytes": int(downloaded_bytes),
        "speed_bps": float(speed_bps),
        "eta_seconds": eta_seconds,
    }
    _set_live_progress(job_id, **values)
    if persist:
        _set_job(session_factory, job_id, **values)


async def _fetch_nzb(url: str) -> bytes:
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=True, headers={"User-Agent": "ScarletX/0.3.9"}) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.content
    except httpx.HTTPError as exc:
        raise NativeUsenetError(f"Could not download NZB: {exc}") from exc
    if not payload.strip():
        raise NativeUsenetError("Indexer returned an empty NZB")
    return payload


async def process_job(session_factory, settings, job_id: str) -> None:
    with _CANCELLED_JOBS_LOCK:
        _CANCELLED_JOBS.discard(job_id)
    with session_factory() as db:
        job = db.get(NativeUsenetJob, job_id)
        if job is None or job.status not in {"queued", "downloading", "postprocessing", "paused"}:
            return
        title = job.title
        url = job.nzb_url
        unpack_password = job.unpack_password or ""

    providers = [p for p in settings.native_usenet_providers() if p.enabled and p.host]
    if not providers:
        _set_job(session_factory, job_id, status="failed", error="No enabled Usenet provider is configured", completed_at=utcnow(), unpack_password=None)
        return

    incomplete_root = Path(settings.native_usenet_incomplete_dir).expanduser().resolve()
    complete_root = Path(settings.native_usenet_complete_dir).expanduser().resolve()
    failed_root = incomplete_root.parent / "failed"
    work = incomplete_root / job_id

    # A retry resumes from preserved work instead of starting from zero.
    with session_factory() as db:
        current = db.get(NativeUsenetJob, job_id)
        prior_path = Path(current.output_path).expanduser() if current and current.output_path else None
    if prior_path and prior_path.exists() and failed_root in prior_path.resolve().parents:
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
        incomplete_root.mkdir(parents=True, exist_ok=True)
        shutil.move(str(prior_path), str(work))
        _set_job(session_factory, job_id, output_path=None)

    payload_dir = work / "payload"
    state_root = work / "segments"      # tiny resume markers only in 0.3.6+
    assembly_root = work / "assembly"   # sparse/preallocated target files
    payload_dir.mkdir(parents=True, exist_ok=True)
    state_root.mkdir(parents=True, exist_ok=True)
    assembly_root.mkdir(parents=True, exist_ok=True)

    try:
        _set_job(session_factory, job_id, status="downloading", error=None, started_at=utcnow(), postprocess_note=None)
        nzb_file = work / "source.nzb"
        if nzb_file.exists() and nzb_file.stat().st_size:
            nzb_payload = nzb_file.read_bytes()
        else:
            nzb_payload = await _fetch_nzb(url)
            nzb_file.write_bytes(nzb_payload)
        files = parse_nzb(nzb_payload)

        file_states: dict[int, dict] = {}
        primary_indices: list[int] = []
        deferred_indices: list[int] = []
        optional_indices: list[int] = []

        for file_index, item in enumerate(files, 1):
            priority, deferred = _file_download_priority(item, file_index)
            state_dir = state_root / f"{file_index:04d}"
            state_dir.mkdir(parents=True, exist_ok=True)
            assembly = assembly_root / f"{file_index:04d}.part"
            filename_marker = state_dir / "filename.txt"

            # 0.3.5 compatibility: if every legacy .seg exists, assemble it once and
            # convert to tiny .done markers. Partial legacy files are redownloaded for
            # this NZB file because yEnc positional offsets were not persisted before.
            legacy = sorted(state_dir.glob("*.seg"))
            done = sorted(state_dir.glob("*.done"))
            if legacy and not done:
                if len(legacy) == len(item.segments) and all(x.stat().st_size > 0 for x in legacy):
                    with assembly.open("wb", buffering=1024 * 1024) as output:
                        offset = 1
                        for segment, part in zip(item.segments, legacy):
                            size = part.stat().st_size
                            with part.open("rb") as source:
                                shutil.copyfileobj(source, output, length=4 * 1024 * 1024)
                            _write_done_marker(state_dir / f"{segment.number:06d}.done", size, offset, None)
                            offset += size
                    for part in legacy:
                        part.unlink(missing_ok=True)
                else:
                    for part in legacy:
                        part.unlink(missing_ok=True)

            file_states[file_index] = {
                "item": item,
                "priority": priority,
                "deferred": deferred,
                "state_dir": state_dir,
                "assembly": assembly,
                "filename_marker": filename_marker,
            }
            if deferred:
                deferred_indices.append(file_index)
            elif priority >= 70:
                optional_indices.append(file_index)
            else:
                primary_indices.append(file_index)

        # An unusual NZB containing only support/recovery files should still be downloadable.
        if not primary_indices:
            primary_indices = optional_indices or deferred_indices
            if primary_indices is optional_indices:
                optional_indices = []
            else:
                deferred_indices = []
            for idx in primary_indices:
                file_states[idx]["deferred"] = False

        def completed_bytes(indices: list[int]) -> int:
            total_done = 0
            for idx in indices:
                state = file_states[idx]
                item: NZBFile = state["item"]
                for segment in item.segments:
                    total_done += _read_done_marker(state["state_dir"] / f"{segment.number:06d}.done")
            return total_done

        def advertised_bytes(indices: list[int]) -> int:
            return sum(segment.bytes for idx in indices for segment in file_states[idx]["item"].segments)

        def finalize_files(indices: list[int]) -> None:
            for idx in indices:
                state = file_states[idx]
                item: NZBFile = state["item"]
                state_dir: Path = state["state_dir"]
                assembly: Path = state["assembly"]
                markers = [state_dir / f"{segment.number:06d}.done" for segment in item.segments]
                if not all(_read_done_marker(marker) > 0 for marker in markers):
                    raise NativeUsenetError(f"Missing segments for NZB file {idx}")
                filename_marker: Path = state["filename_marker"]
                if filename_marker.exists():
                    filename = _safe_filename(filename_marker.read_text(errors="ignore"), f"file-{idx:04d}.bin")
                else:
                    filename = _safe_filename(_subject_filename(item.subject, idx), f"file-{idx:04d}.bin")
                    filename_marker.write_text(filename)
                destination = payload_dir / filename
                fetcher.close_target(assembly)
                if destination.exists() and not assembly.exists():
                    continue
                if destination.exists() and assembly.exists():
                    # Distinct NZB files can occasionally report the same obfuscated name.
                    destination = payload_dir / f"{idx:04d}-{filename}"
                if not assembly.exists():
                    raise NativeUsenetError(f"Assembled payload missing for NZB file {idx}")
                assembly.replace(destination)

        effective_total = advertised_bytes(primary_indices)
        existing = completed_bytes(primary_indices)
        downloaded = existing
        session_downloaded = 0
        transfer_started = time.monotonic()
        speed_samples = deque([(transfer_started, 0)], maxlen=256)
        last_progress_persist = 0.0
        last_control_check = 0.0
        _set_job(session_factory, job_id, total_bytes=effective_total, downloaded_bytes=downloaded)

        hard_cap = min(
            max(1, int(settings.native_usenet_max_connections)),
            max(1, sum(p.connections for p in providers)),
            150,
        )
        # Start modestly and ramp quickly. This reaches 100+ sessions in seconds when
        # throughput keeps improving but avoids paying TLS/thread overhead unnecessarily.
        active_window = min(hard_cap, 12 if hard_cap >= 12 else hard_cap)
        fetcher = _shared_segment_fetcher(providers, settings.native_usenet_max_retries)
        with _ACTIVE_FETCHERS_LOCK:
            _ACTIVE_FETCHERS[job_id] = fetcher
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=hard_cap, thread_name_prefix="scarletx-nntp")

        async def download_indices(indices: list[int], *, recovery: bool = False) -> None:
            nonlocal downloaded, session_downloaded, effective_total, last_progress_persist, last_control_check, active_window
            jobs: list[tuple[int, int, int, NZBSegment, Path, Path, Path]] = []
            for idx in indices:
                state = file_states[idx]
                item: NZBFile = state["item"]
                for segment in item.segments:
                    done_marker = state["state_dir"] / f"{segment.number:06d}.done"
                    if _read_done_marker(done_marker) > 0 and (state["assembly"].exists() or (state["filename_marker"].exists() and (payload_dir / _safe_filename(state["filename_marker"].read_text(errors="ignore"), f"file-{idx:04d}.bin")).exists())):
                        continue
                    jobs.append((state["priority"], idx, segment.number, segment, state["assembly"], done_marker, state["filename_marker"]))
            jobs.sort(key=lambda row: (row[0], row[2], row[1]))
            if not jobs:
                finalize_files(indices)
                return

            loop = asyncio.get_running_loop()
            position = 0
            inflight: dict[asyncio.Future, tuple[int, Path]] = {}
            tune_time = time.monotonic()
            tune_speed = 0.0
            stable_rounds = 0

            def submit_until_window() -> None:
                nonlocal position
                while len(inflight) < active_window and position < len(jobs):
                    _, idx, _, segment, target, done_marker, filename_marker = jobs[position]
                    position += 1
                    future = loop.run_in_executor(executor, fetcher.fetch_into, segment, target, done_marker)
                    inflight[future] = (idx, filename_marker)

            submit_until_window()
            while inflight:
                now = time.monotonic()
                if now - last_control_check >= 0.35:
                    await _wait_if_paused(session_factory, job_id)
                    last_control_check = now

                done, _ = await asyncio.wait(set(inflight), timeout=0.20, return_when=asyncio.FIRST_COMPLETED)
                if done:
                    for future in done:
                        idx, filename_marker = inflight.pop(future)
                        result = future.result()
                        downloaded += result.size
                        session_downloaded += result.size
                        if result.filename and not filename_marker.exists():
                            try:
                                temp = filename_marker.with_name("filename.txt.tmp")
                                temp.write_text(_safe_filename(result.filename, f"file-{idx:04d}.bin"))
                                temp.replace(filename_marker)
                            except Exception:
                                pass

                now = time.monotonic()
                speed_samples.append((now, session_downloaded))
                while len(speed_samples) > 2 and now - speed_samples[0][0] > 4.0:
                    speed_samples.popleft()
                first_t, first_bytes = speed_samples[0]
                speed = max(0.0, (session_downloaded - first_bytes) / max(0.001, now - first_t))
                eta = int(max(0, effective_total - downloaded) / speed) if speed > 0 else None

                # Adaptive connection tuning. Ramp while aggregate throughput improves,
                # but also back off if excessive concurrency materially hurts the
                # rolling transfer rate. This finds a useful working set instead of
                # assuming that the largest configured connection count is fastest.
                if now - tune_time >= 1.5:
                    minimum_probe = min(32, hard_cap)
                    should_grow = active_window < minimum_probe or tune_speed <= 0 or speed >= tune_speed * 1.03
                    severe_drop = tune_speed > 0 and speed < tune_speed * 0.72
                    if should_grow and active_window < hard_cap:
                        new_window = min(hard_cap, max(active_window + 4, int(active_window * 1.5)))
                        if new_window > active_window:
                            active_window = new_window
                        stable_rounds = 0
                    elif severe_drop and active_window > 12:
                        stable_rounds += 1
                        if stable_rounds >= 2:
                            active_window = max(12, minimum_probe if active_window <= minimum_probe else int(active_window * 0.75))
                            stable_rounds = 0
                    else:
                        stable_rounds += 1
                    # Decay the comparison baseline so the scheduler can re-probe a
                    # higher connection count after a temporary network/server dip.
                    tune_speed = max(speed, tune_speed * 0.985)
                    tune_time = now

                persist = now - last_progress_persist >= 1.0
                _publish_progress(
                    session_factory, job_id,
                    total_bytes=effective_total, downloaded_bytes=downloaded,
                    speed_bps=speed, eta_seconds=eta, persist=persist,
                )
                _set_live_progress(
                    job_id,
                    provider=fetcher.best_provider(),
                    provider_stats=fetcher.provider_stats(),
                    active_connections=active_window,
                    connection_cap=hard_cap,
                    phase="recovery" if recovery else "payload",
                )
                if persist:
                    last_progress_persist = now

                limit = float(settings.native_usenet_speed_limit_mb_s or 0)
                if limit > 0 and session_downloaded > 0:
                    target_elapsed = session_downloaded / (limit * 1024 * 1024)
                    actual_elapsed = time.monotonic() - transfer_started
                    if target_elapsed > actual_elapsed:
                        await asyncio.sleep(target_elapsed - actual_elapsed)

                submit_until_window()

            finalize_files(indices)
            final_now = time.monotonic()
            first_t, first_bytes = speed_samples[0]
            final_speed = max(0.0, (session_downloaded - first_bytes) / max(0.001, final_now - first_t))
            final_eta = int(max(0, effective_total - downloaded) / final_speed) if final_speed > 0 else None
            _publish_progress(
                session_factory, job_id,
                total_bytes=effective_total, downloaded_bytes=downloaded,
                speed_bps=final_speed, eta_seconds=final_eta, persist=True,
            )
            last_progress_persist = final_now

        try:
            await download_indices(primary_indices)

            _set_job(session_factory, job_id, status="postprocessing", speed_bps=0.0, eta_seconds=0, postprocess_note="Fast-path media detection")
            notes: list[str] = []
            if optional_indices:
                skipped_support = advertised_bytes(optional_indices)
                notes.append(f"Skipped {skipped_support / 1024 / 1024:.1f} MB of nonessential NFO/SFV/image support files")
            best_name = fetcher.best_provider()
            if best_name:
                best_stat = next((x for x in fetcher.provider_stats() if x["name"] == best_name), None)
                if best_stat and best_stat.get("speed_bps"):
                    notes.append(f"Fastest provider: {best_name} ({float(best_stat['speed_bps']) / 1024 / 1024:.1f} MB/s/article)")
                else:
                    notes.append(f"Fastest provider: {best_name}")

            def post_stage(message: str) -> None:
                prefix = (notes[0] + "; ") if notes else ""
                _set_job(session_factory, job_id, postprocess_note=(prefix + message)[:2000])

            # First try without PAR2 recovery volumes. Healthy direct videos and healthy
            # archive sets therefore never download gigabytes of recovery data.
            fast_error: Exception | None = None
            try:
                fast_notes, videos = await asyncio.to_thread(
                    postprocess_payload,
                    payload_dir,
                    repair_enabled=False,
                    unpack_enabled=settings.native_usenet_unpack_enabled,
                    password=unpack_password,
                    job_id=job_id,
                    stage=post_stage,
                )
                notes.extend(fast_notes)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                fast_error = exc
                videos = []

            if videos and deferred_indices:
                skipped = advertised_bytes(deferred_indices)
                notes.append(f"Skipped {skipped / 1024 / 1024:.1f} MB of unnecessary PAR2 recovery volumes")
            elif deferred_indices:
                recovery_total = advertised_bytes(deferred_indices)
                recovery_existing = completed_bytes(deferred_indices)
                effective_total += recovery_total
                downloaded += recovery_existing
                _set_job(
                    session_factory, job_id, status="downloading",
                    total_bytes=effective_total, downloaded_bytes=downloaded,
                    postprocess_note="Fetching PAR2 recovery volumes only because the primary payload needs repair",
                )
                await download_indices(deferred_indices, recovery=True)
                _set_job(session_factory, job_id, status="postprocessing", speed_bps=0.0, eta_seconds=0, postprocess_note="Repairing recovered payload")
                post_notes, videos = await asyncio.to_thread(
                    postprocess_payload,
                    payload_dir,
                    repair_enabled=settings.native_usenet_repair_enabled,
                    unpack_enabled=settings.native_usenet_unpack_enabled,
                    password=unpack_password,
                    job_id=job_id,
                    stage=post_stage,
                )
                notes.extend(post_notes)
            elif not videos:
                # No deferred volumes exist, so give the normal repair path one chance.
                post_notes, videos = await asyncio.to_thread(
                    postprocess_payload,
                    payload_dir,
                    repair_enabled=settings.native_usenet_repair_enabled,
                    unpack_enabled=settings.native_usenet_unpack_enabled,
                    password=unpack_password,
                    job_id=job_id,
                    stage=post_stage,
                )
                notes.extend(post_notes)

            if not videos:
                names = ", ".join(p.name for p in sorted(payload_dir.rglob("*")) if p.is_file())[:1200]
                suffix = f"; fast path: {fast_error}" if fast_error else ""
                raise NativeUsenetError(
                    "Download finished but no playable scene video was found after de-obfuscation, repair, and unpack"
                    + (f": {names}" if names else "") + suffix
                )

            primary = videos[0]
            notes.append(f"Primary scene: {primary.name} ({primary.stat().st_size} bytes)")
            complete_root.mkdir(parents=True, exist_ok=True)
            final_name = _safe_filename(title, job_id)
            final_dir = _unique_directory(complete_root / final_name)
            shutil.move(str(payload_dir), str(final_dir))
            shutil.rmtree(work, ignore_errors=True)
            _set_job(
                session_factory,
                job_id,
                status="completed",
                total_bytes=max(downloaded, effective_total),
                downloaded_bytes=max(downloaded, effective_total),
                speed_bps=0.0,
                eta_seconds=0,
                output_path=str(final_dir),
                postprocess_note="; ".join(dict.fromkeys(notes))[:2000] if notes else "Download complete",
                completed_at=utcnow(),
                unpack_password=None,
            )
            _clear_live_progress(job_id)
            with _CANCELLED_JOBS_LOCK:
                _CANCELLED_JOBS.discard(job_id)
        except BaseException:
            # Wake all in-flight BODY reads before joining executor workers. The shared
            # pool remains reusable; broken leases release and fresh sockets are opened.
            fetcher.abort_active()
            raise
        finally:
            with _ACTIVE_FETCHERS_LOCK:
                _ACTIVE_FETCHERS.pop(job_id, None)
            executor.shutdown(wait=True, cancel_futures=True)
            fetcher.close_targets_under(assembly_root)

    except asyncio.CancelledError:
        shutil.rmtree(work, ignore_errors=True)
        _set_job(session_factory, job_id, status="cancelled", speed_bps=0.0, eta_seconds=0, output_path=None, error=None, completed_at=utcnow(), unpack_password=None)
        _clear_live_progress(job_id)
        with _CANCELLED_JOBS_LOCK:
            _CANCELLED_JOBS.discard(job_id)
        with session_factory() as db:
            tracked = db.scalar(select(TrackedDownload).where(TrackedDownload.nzo_id == job_id))
            if tracked:
                tracked.status = "cancelled"
                tracked.client_status = "cancelled"
                tracked.error = None
                tracked.completed_at = utcnow()
                tracked.last_checked_at = utcnow()
                db.commit()
    except Exception as exc:
        message = str(exc)[:4000]
        failed_path = None
        try:
            failed_root.mkdir(parents=True, exist_ok=True)
            if work.exists():
                failed_dir = _unique_directory(failed_root / f"{_safe_filename(title, job_id)} -- {job_id[-8:]}")
                shutil.move(str(work), str(failed_dir))
                failed_path = str(failed_dir)
        except Exception:
            failed_path = str(work) if work.exists() else None
        _set_job(session_factory, job_id, status="failed", error=message, speed_bps=0.0, eta_seconds=0, output_path=failed_path, completed_at=utcnow(), unpack_password=None)
        _clear_live_progress(job_id)
        with _CANCELLED_JOBS_LOCK:
            _CANCELLED_JOBS.discard(job_id)
        with session_factory() as db:
            tracked = db.scalar(select(TrackedDownload).where(TrackedDownload.nzo_id == job_id))
            if tracked:
                tracked.status = "failed"
                tracked.client_status = "failed"
                tracked.error = message
                tracked.last_checked_at = utcnow()
                db.add(History(event_type="download_failed", scene_id=tracked.scene_id, message=f"Built-in download failed: {tracked.scene_title or tracked.release_title}"))
                db.commit()


async def native_worker_loop(session_factory, settings_loader, poll_seconds: float = 1.0) -> None:
    emit_status("Native Downloader", "ACTIVE", f"poll every {poll_seconds:g}s", severity="active")
    # Jobs interrupted by an app restart are safe to retry because decoded segments
    # are persisted under the incomplete directory and skipped on the next pass.
    with session_factory() as db:
        db.execute(update(NativeUsenetJob).where(NativeUsenetJob.status.in_(["downloading", "postprocessing"])).values(status="queued", speed_bps=0.0, eta_seconds=None))
        db.commit()
    while True:
        with session_factory() as db:
            job = db.scalar(select(NativeUsenetJob).where(NativeUsenetJob.status == "queued").order_by(NativeUsenetJob.created_at.asc()).limit(1))
            job_id = job.id if job else None
        if not job_id:
            await asyncio.sleep(poll_seconds)
            continue
        settings = settings_loader()
        await process_job(session_factory, settings, job_id)


def queue_rows(db, *, active_only: bool = True, limit: int = 200) -> list[dict]:
    stmt = select(NativeUsenetJob)
    if active_only:
        stmt = stmt.where(NativeUsenetJob.status.in_(["queued", "downloading", "paused", "postprocessing"]))
    rows = db.scalars(stmt.order_by(NativeUsenetJob.created_at.asc()).limit(limit)).all()
    return [job_dict(row) for row in rows]


def completed_rows(db, limit: int = 100) -> list[dict]:
    rows = db.scalars(select(NativeUsenetJob).where(NativeUsenetJob.status == "completed").order_by(NativeUsenetJob.completed_at.desc()).limit(limit)).all()
    return [job_dict(row) for row in rows]


def history_rows(db, limit: int = 100) -> list[dict]:
    rows = db.scalars(select(NativeUsenetJob).where(NativeUsenetJob.status.in_(["completed", "cancelled"])).order_by(NativeUsenetJob.created_at.desc()).limit(limit)).all()
    return [job_dict(row) for row in rows]


def failed_rows(db, limit: int = 200) -> list[dict]:
    rows = db.scalars(select(NativeUsenetJob).where(NativeUsenetJob.status == "failed").order_by(NativeUsenetJob.updated_at.desc()).limit(limit)).all()
    return [job_dict(row) for row in rows]


def job_dict(job: NativeUsenetJob) -> dict:
    live = _get_live_progress(job.id)
    total = max(0, int(live.get("total_bytes", job.total_bytes or 0) or 0))
    done = max(0, int(live.get("downloaded_bytes", job.downloaded_bytes or 0) or 0))
    speed_bps = float(live.get("speed_bps", job.speed_bps or 0) or 0)
    eta_seconds = live.get("eta_seconds", job.eta_seconds)
    progress = min(100.0, (done / total * 100.0) if total else 0.0)
    return {
        "id": job.id,
        "title": job.title,
        "status": job.status,
        "total_bytes": total,
        "downloaded_bytes": done,
        "progress": round(progress, 2),
        "speed_bps": speed_bps,
        "eta_seconds": eta_seconds,
        "provider": live.get("provider"),
        "provider_stats": live.get("provider_stats", []),
        "active_connections": live.get("active_connections"),
        "connection_cap": live.get("connection_cap"),
        "phase": live.get("phase"),
        "output_path": job.output_path,
        "error": job.error,
        "postprocess_note": job.postprocess_note,
        "unpack_password_configured": bool(job.unpack_password),
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
    }
