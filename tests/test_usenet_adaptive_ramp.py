from scarletx.usenet.worker import _initial_active_window, _tune_active_window


def test_large_cap_starts_with_thirty_two_workers():
    assert _initial_active_window(150) == 32


def test_small_cap_never_exceeds_cap():
    assert _initial_active_window(20) == 20


def test_tuner_grows_aggressively_toward_provider_capacity():
    window = 32
    stable_drop_rounds = 0
    for current_speed, baseline_speed in [
        (10.0, 0.0),
        (10.1, 10.0),
        (10.0, 10.1),
        (10.2, 10.1),
    ]:
        window, stable_drop_rounds = _tune_active_window(
            active_window=window,
            hard_cap=150,
            speed=current_speed,
            tune_speed=baseline_speed,
            stable_drop_rounds=stable_drop_rounds,
        )
    assert window == 150


def test_single_short_speed_drop_does_not_back_off():
    window, drop_rounds = _tune_active_window(
        active_window=108,
        hard_cap=150,
        speed=6.0,
        tune_speed=10.0,
        stable_drop_rounds=0,
    )
    assert window == 108
    assert drop_rounds == 1


def test_backoff_requires_three_consecutive_severe_drops():
    window = 108
    drop_rounds = 0
    for _ in range(2):
        window, drop_rounds = _tune_active_window(
            active_window=window,
            hard_cap=150,
            speed=6.0,
            tune_speed=10.0,
            stable_drop_rounds=drop_rounds,
        )
    assert window == 108
    assert drop_rounds == 2

    window, drop_rounds = _tune_active_window(
        active_window=window,
        hard_cap=150,
        speed=6.0,
        tune_speed=10.0,
        stable_drop_rounds=drop_rounds,
    )
    assert window == 81
    assert drop_rounds == 0
