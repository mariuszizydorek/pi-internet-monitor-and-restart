import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[1] / "scripts" / "setup-grafana.py"
_spec = importlib.util.spec_from_file_location("setup_grafana", _path)
setup_grafana = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(setup_grafana)


def test_setup_writes_supabase_without_touching_other_settings(tmp_path):
    env = tmp_path / "netwatch.env"
    env.write_text("SITE_ID=pi2\nDECO_HOST=192.168.68.1\n", encoding="utf-8")

    setup_grafana.run_setup(
        tmp_path,
        "https://example.supabase.co/rest/v1",
        "sb_secret_example",
        "admin-secret",
    )

    text = env.read_text(encoding="utf-8")
    assert "SITE_ID=pi2" in text
    assert "DECO_HOST=192.168.68.1" in text
    assert "SUPABASE_URL=https://example.supabase.co" in text
    assert (tmp_path / "secrets" / "supabase_key").read_text(encoding="utf-8") == "sb_secret_example\n"
    assert (tmp_path / "secrets" / "grafana_admin_password").read_text(encoding="utf-8") == "admin-secret\n"


def test_setup_rejects_the_publishable_key(tmp_path):
    try:
        setup_grafana.run_setup(tmp_path, "https://example.supabase.co", "sb_publishable_x", "pw")
    except SystemExit as exc:
        assert "publishable" in str(exc)
    else:
        raise AssertionError("publishable key was accepted")
