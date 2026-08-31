from scarletx import native_usenet


def _limiter():
    limiter = getattr(native_usenet, "_interactive_connection_cap", None)
    assert callable(limiter), "downloader needs a CPU-aware interactive connection cap"
    return limiter


def test_two_cpu_native_decoder_reserves_web_headroom():
    assert _limiter()(120, effective_cpus=2, native_acceleration=True) == 16


def test_two_cpu_fallback_decoder_uses_lower_cap():
    assert _limiter()(120, effective_cpus=2, native_acceleration=False) == 8


def test_explicit_lower_connection_limit_is_preserved():
    assert _limiter()(6, effective_cpus=8, native_acceleration=True) == 6


def test_large_machine_can_still_use_full_configured_limit():
    assert _limiter()(120, effective_cpus=16, native_acceleration=True) == 120
