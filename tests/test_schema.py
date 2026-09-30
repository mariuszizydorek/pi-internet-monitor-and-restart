import httpx

from netwatch.sync.schema import apply_sql_dir, sql_statements


def test_sql_statements_skip_comments():
    statements = sql_statements("-- note\ncreate table t (id int);\n\ncreate index i on t (id);\n")
    assert statements == ["create table t (id int);", "create index i on t (id);"]


def test_apply_sql_dir_posts_each_statement(tmp_path):
    sql = tmp_path / "001_init.sql"
    sql.write_text("create table interface_samples (id int);\n", encoding="utf-8")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers["Authorization"], request.read().decode()))
        return httpx.Response(201, json=[])

    applied = apply_sql_dir(
        "https://example.supabase.co",
        "sbp_token",
        tmp_path,
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert applied == ["001_init.sql"]
    assert seen[0][0] == "https://api.supabase.com/v1/projects/example/database/query"
    assert seen[0][1] == "Bearer sbp_token"
    assert "interface_samples" in seen[0][2]
