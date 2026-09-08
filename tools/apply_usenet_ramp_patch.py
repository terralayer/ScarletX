from pathlib import Path

path = Path("scarletx/usenet/worker.py")
text = path.read_text()

anchor = '''class NativeUsenetError(RuntimeError):
    pass


class UsenetProviderConfig(BaseModel):
'''
replacement = '''class NativeUsenetError(RuntimeError):
    pass


def _initial_active_window(hard_cap: int) -> int:
    """Start large downloads with enough parallel BODY work to fill fast links."""
    return min(max(1, int(hard_cap)), 32)


def _tune_active_window(
    *,
    active_window: int,
    hard_cap: int,
    speed: float,
    tune_speed: float,
    stable_drop_rounds: int,
) -> tuple[int, int]:
    """Ramp quickly and back off only after a sustained severe throughput drop."""
    cap = max(1, int(hard_cap))
    window = min(cap, max(1, int(active_window)))
    severe_drop = tune_speed > 0 and speed < tune_speed * 0.70

    if severe_drop:
        drop_rounds = max(0, int(stable_drop_rounds)) + 1
        if drop_rounds >= 3 and window > 32:
            return max(32, int(window * 0.75)), 0
        return window, drop_rounds

    if window < cap:
        return min(cap, max(window + 16, int(window * 1.5))), 0
    return window, 0


class UsenetProviderConfig(BaseModel):
'''
assert text.count(anchor) == 1, "helper insertion anchor did not match exactly once"
text = text.replace(anchor, replacement, 1)

old_initial = '''        # Start modestly and ramp quickly. This reaches 100+ sessions in seconds when
        # throughput keeps improving but avoids paying TLS/thread overhead unnecessarily.
        active_window = min(hard_cap, 12 if hard_cap >= 12 else hard_cap)
'''
new_initial = '''        # Start with enough parallel BODY requests to fill fast links, then let the
        # adaptive tuner ramp toward provider capacity while preserving backoff.
        active_window = _initial_active_window(hard_cap)
'''
assert text.count(old_initial) == 1, "initial-window block did not match exactly once"
text = text.replace(old_initial, new_initial, 1)

old_tuner = '''                # Adaptive connection tuning. Ramp while aggregate throughput improves,
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
'''
new_tuner = '''                # Usenet article completion is bursty, so grow aggressively through
                # normal short-term variation and only back off after a sustained drop.
                if now - tune_time >= 1.5:
                    active_window, stable_rounds = _tune_active_window(
                        active_window=active_window,
                        hard_cap=hard_cap,
                        speed=speed,
                        tune_speed=tune_speed,
                        stable_drop_rounds=stable_rounds,
                    )
                    # Decay the comparison baseline so the scheduler can re-probe a
                    # higher connection count after a temporary network/server dip.
                    tune_speed = max(speed, tune_speed * 0.985)
                    tune_time = now
'''
assert text.count(old_tuner) == 1, "adaptive-tuner block did not match exactly once"
text = text.replace(old_tuner, new_tuner, 1)

path.write_text(text)
