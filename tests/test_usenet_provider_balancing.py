from scarletx.usenet.worker import NZBSegment, SegmentFetcher, UsenetProviderConfig


class _FakePool:
    def __init__(self, limit: int):
        self.limit = limit
        self.leased = 0

    def utilization(self) -> float:
        return self.leased / self.limit


def _fetcher() -> SegmentFetcher:
    providers = [
        UsenetProviderConfig(name="Astraweb", host="astra.example", connections=50, priority=1),
        UsenetProviderConfig(name="Newshosting", host="news.example", connections=100, priority=1),
    ]
    fetcher = SegmentFetcher(providers, max_retries=2)
    fetcher.pools = {
        "Astraweb": _FakePool(50),
        "Newshosting": _FakePool(100),
    }
    for provider in providers:
        fetcher.perf[provider.name]["samples"] = 10
    # Deliberately make Astraweb look much faster. Capacity balancing must still
    # keep both providers productively filled instead of starving Newshosting.
    fetcher.perf["Astraweb"]["ewma_bps"] = 100_000_000.0
    fetcher.perf["Newshosting"]["ewma_bps"] = 10_000_000.0
    return fetcher


def test_provider_order_fills_pools_in_configured_capacity_ratio():
    fetcher = _fetcher()
    segment = NZBSegment(number=1, bytes=1_000_000, message_id="article")

    for _ in range(150):
        provider = fetcher._provider_order(segment)[0]
        pool = fetcher.pools[provider.name]
        if pool.leased < pool.limit:
            pool.leased += 1

    assert fetcher.pools["Astraweb"].leased == 50
    assert fetcher.pools["Newshosting"].leased == 100


def test_saturated_provider_is_not_selected_as_primary():
    fetcher = _fetcher()
    fetcher.pools["Astraweb"].leased = 50
    fetcher.pools["Newshosting"].leased = 25
    segment = NZBSegment(number=1, bytes=1_000_000, message_id="article")

    assert fetcher._provider_order(segment)[0].name == "Newshosting"


def test_reliability_still_breaks_ties_between_equally_loaded_providers():
    fetcher = _fetcher()
    fetcher.pools["Astraweb"].leased = 25
    fetcher.pools["Newshosting"].leased = 50
    fetcher.perf["Astraweb"]["ewma_bps"] = 10_000_000.0
    fetcher.perf["Newshosting"]["ewma_bps"] = 10_000_000.0
    fetcher.perf["Astraweb"]["failures"] = 20
    segment = NZBSegment(number=1, bytes=1_000_000, message_id="article")

    assert fetcher._provider_order(segment)[0].name == "Newshosting"
