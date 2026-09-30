from datetime import datetime, timedelta, timezone

import httpx

from netwatch.config import ConfigError, load_settings, redact
from netwatch.db import Database
from netwatch.restart.gpio import NullPin
from netwatch.restart.service import recover_pin, run_cycle, site_recovered
from netwatch.sync.client import SupabaseRest, row_for_remote
from netwatch.timeutil import iso
from scripts.setup import run_setup


def test_site_id_is_required(monkeypatch):
    monkeypatch.delenv("SITE_ID", raising=False)
    monkeypatch.setenv("NETWATCH_ENV", "/does/not/exist")
    try:
        load_settings()
    except ConfigError as exc:
        assert "SITE_ID" in str(exc)
    else:
        raise AssertionError("expected ConfigError")


def test_secret_file_is_not_copied_into_env(tmp_path, monkeypatch):
    env = tmp_path / "netwatch.env"
    env.write_text("SITE_ID=site-a\n", encoding="utf-8")
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "deco_password").write_text("s3cret\n", encoding="utf-8")
    monkeypatch.setenv("NETWATCH_ENV", str(env))
    monkeypatch.setenv("SECRETS_DIR", str(secrets))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = load_settings()
    assert settings.secret("deco_password") == "s3cret"
    assert "s3cret" not in env.read_text(encoding="utf-8")
    assert redact("login failed for s3cret", ["s3cret"]) == "login failed for ***"


def test_setup_writes_root_only_secrets(tmp_path):
    run_setup(
        tmp_path,
        True,
        {
            "SITE_ID": "site-a",
            "DECO_HOST": "192.168.68.1",
            "DECO_USER": "admin",
            "INTERFACES": "eth0,wlan0",
            "SUPABASE_URL": "https://example.supabase.co",
            "DECO_PASSWORD": "router-secret",
            "SUPABASE_KEY": "service-role",
            "GPIO_ENABLED": "no",
            "GRAFANA_ADMIN_PASSWORD": "grafana-secret",
        },
    )
    env = (tmp_path / "netwatch.env").read_text(encoding="utf-8")
    assert "SITE_ID=site-a" in env
    assert "router-secret" not in env
    assert "service-role" not in env
    password = tmp_path / "secrets" / "deco_password"
    assert password.read_text(encoding="utf-8").strip() == "router-secret"
    assert (password.stat().st_mode & 0o777) == 0o600
    assert (tmp_path / "secrets" / "supabase_key").read_text(encoding="utf-8").strip() == "service-role"
    assert (tmp_path / "secrets" / "grafana_admin_password").read_text(encoding="utf-8").strip() == "grafana-secret"
    assert not (tmp_path / "secrets" / "supabase_db_password").exists()


def test_update_supabase_replaces_only_the_url_and_key(tmp_path):
    env = tmp_path / "netwatch.env"
    env.write_text("SITE_ID=localDev\nSUPABASE_URL=https://old.supabase.co\nINTERFACES=en0\n", encoding="utf-8")
    (tmp_path / "secrets").mkdir()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["apikey"] == "sb_secret_example"
        return httpx.Response(200, json=[])

    url = run_setup_update(
        tmp_path,
        "https://example.supabase.co/rest/v1",
        "sb_secret_example",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    text = env.read_text(encoding="utf-8")
    assert url == "https://example.supabase.co"
    assert "SUPABASE_URL=https://example.supabase.co\n" in text
    assert "SITE_ID=localDev" in text
    assert "INTERFACES=en0" in text
    assert (tmp_path / "secrets" / "supabase_key").read_text(encoding="utf-8").strip() == "sb_secret_example"


def test_update_supabase_refuses_the_publishable_key(tmp_path):
    env = tmp_path / "netwatch.env"
    env.write_text("SITE_ID=localDev\nSUPABASE_URL=https://old.supabase.co\n", encoding="utf-8")
    try:
        run_setup_update(tmp_path, "https://example.supabase.co", "sb_publishable_example", None)
    except SystemExit as exc:
        assert "publishable" in str(exc)
    else:
        raise AssertionError("expected SystemExit")
    assert "old.supabase.co" in env.read_text(encoding="utf-8")
    assert not (tmp_path / "secrets" / "supabase_key").exists()


def run_setup_update(root, url, api_key, http):
    from scripts.setup import update_supabase

    return update_supabase(root, url, api_key, http)


def test_remote_row_uses_local_id_and_parsed_json():
    payload = row_for_remote(
        {
            "id": 7,
            "site_id": "site-a",
            "synced_at": None,
            "probes_json": '{"fetch":{"google":{"ok":true}}}',
        }
    )
    assert payload["local_id"] == 7
    assert "id" not in payload
    assert "synced_at" not in payload
    assert payload["probes_json"]["fetch"]["google"]["ok"] is True


def test_supabase_insert_and_delete():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(201)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    rest = SupabaseRest("https://example.supabase.co", "service-role", http)
    rest.insert("interface_samples", [{"site_id": "site-a", "local_id": 1}])
    assert seen["method"] == "POST"
    assert "on_conflict=site_id%2Clocal_id" in seen["url"] or "on_conflict=site_id,local_id" in seen["url"]
    assert seen["auth"] == "Bearer service-role"
    rest.delete_older("interface_samples", "site-a", "2026-01-01T00:00:00Z")
    assert seen["method"] == "DELETE"
    assert "site_id=eq.site-a" in seen["url"]


def test_startup_drives_the_pin_low_after_a_crash(tmp_path):
    db = Database(tmp_path / "netwatch.sqlite")
    db.migrate()
    now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
    db.mark_pulse_started(now)
    pin = NullPin()
    calls = []
    pin.drive_low = lambda: calls.append("low")  # type: ignore[method-assign]
    from netwatch.config import Settings

    settings = Settings(
        site_id="site-a",
        deco_host="192.168.68.1",
        deco_user="admin",
        interfaces=("eth0", "wlan0"),
        data_dir=tmp_path,
        secrets_dir=tmp_path,
        supabase_url="",
        gpio_enabled=True,
        gpio_chip="gpiochip0",
        gpio_line=17,
    )
    recover_pin(settings, db, pin, now)
    assert calls == ["low"]
    assert db.restart_state().pulse_in_progress is False
    with db.connect() as conn:
        action = conn.execute("SELECT action FROM restart_events").fetchone()["action"]
    assert action == "pin_forced_low"


def test_disabled_gpio_records_one_would_restart(tmp_path):
    db = Database(tmp_path / "netwatch.sqlite")
    db.migrate()
    now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
    for offset in range(0, 21):
        moment = now - timedelta(minutes=20) + timedelta(minutes=offset)
        for iface in ("eth0", "wlan0"):
            db.insert_interface_sample(
                {
                    "site_id": "site-a",
                    "recorded_at": iso(moment),
                    "iface": iface,
                    "carrier": 0,
                    "operstate": "down",
                    "wifi_ssid": None,
                    "wifi_signal_dbm": None,
                    "ipv4": None,
                    "dns_ok": 0,
                    "ping_ok": 0,
                    "fetch_ok": 0,
                    "internet_ok": 0,
                    "probes_json": "{}",
                }
            )
    from netwatch.config import Settings

    settings = Settings(
        site_id="site-a",
        deco_host="192.168.68.1",
        deco_user="admin",
        interfaces=("eth0", "wlan0"),
        data_dir=tmp_path,
        secrets_dir=tmp_path,
        supabase_url="",
        gpio_enabled=False,
        gpio_chip="gpiochip0",
        gpio_line=0,
    )
    memory: dict = {}
    run_cycle(settings, db, NullPin(), now=now, memory=memory)
    run_cycle(settings, db, NullPin(), now=now, memory=memory)
    with db.connect() as conn:
        actions = [row["action"] for row in conn.execute("SELECT action FROM restart_events")]
    assert actions == ["would_restart"]


def test_simulate_restart_does_not_pulse(tmp_path):
    from netwatch.config import Settings
    from netwatch.restart.service import simulate_restart

    db = Database(tmp_path / "netwatch.sqlite")
    db.migrate()
    now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
    for offset in range(0, 21):
        moment = now - timedelta(minutes=20) + timedelta(minutes=offset)
        db.insert_interface_sample(
            {
                "site_id": "site-a",
                "recorded_at": iso(moment),
                "iface": "eth0",
                "carrier": 0,
                "operstate": "down",
                "wifi_ssid": None,
                "wifi_signal_dbm": None,
                "ipv4": None,
                "dns_ok": 0,
                "ping_ok": 0,
                "fetch_ok": 0,
                "internet_ok": 0,
                "probes_json": "{}",
            }
        )
    settings = Settings(
        site_id="site-a",
        deco_host="192.168.68.1",
        deco_user="admin",
        interfaces=("eth0",),
        data_dir=tmp_path,
        secrets_dir=tmp_path,
        supabase_url="",
        gpio_enabled=True,
        gpio_chip="gpiochip0",
        gpio_line=17,
    )
    result = simulate_restart(settings, db, now=now)
    assert result["action"] == "simulated"
    assert result["policy"] == "pulse"
    assert "pin was not driven" in result["detail"]
    assert db.restart_state().pulse_in_progress is False
    assert site_recovered(settings, db, now) is False


def test_gpio_line_required_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("NETWATCH_ENV", str(tmp_path / "missing"))
    monkeypatch.setenv("SITE_ID", "site-a")
    monkeypatch.setenv("GPIO_ENABLED", "true")
    monkeypatch.delenv("GPIO_LINE", raising=False)
    try:
        load_settings()
    except ConfigError as exc:
        assert "GPIO_LINE" in str(exc)
    else:
        raise AssertionError("expected ConfigError")
