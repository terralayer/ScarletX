from scarletx import config


def test_two_cpu_container_reserves_web_headroom(monkeypatch):
    monkeypatch.setattr(config, "_effective_cpu_count", lambda: 2, raising=False)
    settings = config.Settings(native_usenet_max_connections=120)
    assert settings.native_usenet_max_connections == 16


def test_explicit_lower_connection_limit_is_preserved(monkeypatch):
    monkeypatch.setattr(config, "_effective_cpu_count", lambda: 8, raising=False)
    settings = config.Settings(native_usenet_max_connections=6)
    assert settings.native_usenet_max_connections == 6


def test_large_machine_can_still_use_full_configured_limit(monkeypatch):
    monkeypatch.setattr(config, "_effective_cpu_count", lambda: 16, raising=False)
    settings = config.Settings(native_usenet_max_connections=120)
    assert settings.native_usenet_max_connections == 120
