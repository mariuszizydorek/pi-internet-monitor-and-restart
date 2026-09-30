import httpx

from netwatch.localapp.connectivity import check_supabase, connectivity_report


def test_supabase_read_succeeds():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["apikey"] == "secret-key"
        assert request.url.path == "/rest/v1/interface_samples"
        return httpx.Response(200, json=[])

    result = check_supabase(
        "https://example.supabase.co",
        "secret-key",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert result["ok"] is True
    assert result["status"] == 200


def test_supabase_missing_table():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="relation missing")

    result = check_supabase(
        "https://example.supabase.co",
        "secret-key",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert result["ok"] is False
    assert "001_init.sql" in result["detail"]


def test_supabase_rejects_key_without_echoing_it():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="secret-key invalid")

    result = check_supabase(
        "https://example.supabase.co",
        "secret-key",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert result["ok"] is False
    assert "sb_secret_" in result["detail"]
    assert "secret-key" not in result["detail"]


class _Settings:
    site_id = "pi2"
    supabase_url = ""

    def secret(self, name: str) -> str:
        return ""


class _Database:
    def latest_interface(self, site_id: str, iface: str) -> None:
        return None


def test_blank_grafana_url_is_left_off_the_admin_checks():
    report = connectivity_report(
        _Settings(),
        _Database(),
        httpx.Client(),
        "",
    )
    assert [item["name"] for item in report["checks"]] == ["sqlite", "supabase"]
