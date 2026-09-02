from __future__ import annotations

from . import worker as _worker

SegmentFetcher = _worker.SegmentFetcher
UsenetProviderConfig = _worker.UsenetProviderConfig
test_provider = _worker.test_provider
native_client_ready = _worker.native_client_ready

__all__ = ('SegmentFetcher', 'UsenetProviderConfig', 'test_provider', 'native_client_ready')
