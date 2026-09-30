from datetime import datetime, timedelta, timezone

from netwatch.restart.policy import Decision, Observation, decide

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
INTERFACES = ("eth0", "wlan0")


def samples(start: datetime, minutes: int, internet_ok: bool, step: int = 1) -> list[Observation]:
    rows = []
    for offset in range(0, minutes + 1, step):
        moment = start + timedelta(minutes=offset)
        for iface in INTERFACES:
            rows.append(Observation(moment, iface, internet_ok))
    return rows


def run(observations, **overrides) -> Decision:
    params = dict(
        now=NOW,
        interfaces=INTERFACES,
        observations=observations,
        last_pulse_at=None,
        gpio_enabled=True,
        outage_seconds=15 * 60,
        cooldown_seconds=2 * 3600,
        stale_seconds=120,
    )
    params.update(overrides)
    return decide(**params)


def test_pulse_after_fifteen_minutes_down():
    history = samples(NOW - timedelta(minutes=16), 16, False)
    assert run(history).action == "pulse"


def test_wait_when_the_outage_is_shorter_than_fifteen_minutes():
    history = samples(NOW - timedelta(minutes=10), 10, False)
    assert run(history).action == "wait"


def test_up_when_one_interface_can_fetch():
    history = samples(NOW - timedelta(minutes=20), 20, False)
    history.append(Observation(NOW, "wlan0", True))
    assert run(history).action == "up"


def test_skip_when_samples_are_stale():
    history = samples(NOW - timedelta(minutes=20), 16, False)
    assert run(history).action == "skip_stale"


def test_skip_during_cooldown():
    history = samples(NOW - timedelta(minutes=20), 20, False)
    decision = run(history, last_pulse_at=NOW - timedelta(hours=1))
    assert decision.action == "skip_cooldown"


def test_would_restart_when_gpio_is_disabled():
    history = samples(NOW - timedelta(minutes=20), 20, False)
    assert run(history, gpio_enabled=False).action == "would_restart"


def test_recent_success_inside_the_window_keeps_waiting():
    history = samples(NOW - timedelta(minutes=30), 30, False)
    history.append(Observation(NOW - timedelta(minutes=5), "eth0", True))
    history.append(Observation(NOW, "eth0", False))
    history.append(Observation(NOW, "wlan0", False))
    assert run(history).action == "wait"
