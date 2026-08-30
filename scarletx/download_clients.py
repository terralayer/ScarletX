from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .native_usenet import NativeUsenetError, enqueue_url, native_client_ready
from .newznab import NewznabRelease


class DownloadClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class SubmittedDownload:
    client: str
    ids: tuple[str, ...]


def resolve_client(settings: Settings) -> str:
    return "scarletx"


def client_ready(settings: Settings, protocol: str = "usenet") -> bool:
    return native_client_ready(settings)


async def submit_release(
    settings: Settings,
    release: NewznabRelease,
    *,
    session_factory,
    name: str | None = None,
    category: str | None = None,
) -> SubmittedDownload:
    if not release.download_url:
        raise DownloadClientError("Release has no download URL")
    if not native_client_ready(settings):
        raise DownloadClientError("ScarletX built-in Usenet has no enabled NNTP provider configured")
    try:
        job_id = enqueue_url(session_factory, settings, release.download_url, name or release.title)
    except NativeUsenetError as exc:
        raise DownloadClientError(str(exc)) from exc
    return SubmittedDownload(client="scarletx", ids=(job_id,))
