"""API キーの登録（設定画面）と、ほかのサイトからの操作を断る仕組みのテスト。"""
import os

import pytest

from app.providers.openai_provider import OpenAIProvider
from tests.fakes import BASE_URL, ENV_FILE_NAME, image_bytes, make_client

ENV_NAME = "OPENAI_API_KEY"
FAKE_KEY = "sk-test-NotARealKey_0123456789.abcd"


def _env_text(tmp_path):
    path = tmp_path / ENV_FILE_NAME
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_initially_not_configured(client):
    assert client.get("/api/api-keys").json() == [
        {"provider": "openai", "label": "Fake", "env_name": ENV_NAME, "configured": False, "hint": None}
    ]


def test_set_saves_to_env_file_and_takes_effect_immediately(client, tmp_path):
    response = client.put("/api/api-keys/openai", json={"key": FAKE_KEY})

    assert response.status_code == 200
    assert response.json() == {
        "provider": "openai", "label": "Fake", "env_name": ENV_NAME, "configured": True, "hint": "abcd",
    }
    assert _env_text(tmp_path).splitlines() == [f"{ENV_NAME}={FAKE_KEY}"]
    assert os.environ[ENV_NAME] == FAKE_KEY
    # 起動し直さなくても、本物のプロバイダーから使える状態になっている
    assert OpenAIProvider().is_configured()


def test_key_is_never_returned(client):
    put = client.put("/api/api-keys/openai", json={"key": FAKE_KEY})
    listed = client.get("/api/api-keys")
    providers = client.get("/api/providers")

    for response in (put, listed, providers):
        assert FAKE_KEY not in response.text


def test_set_trims_surrounding_whitespace(client, tmp_path):
    client.put("/api/api-keys/openai", json={"key": f"  {FAKE_KEY}\n"})
    assert os.environ[ENV_NAME] == FAKE_KEY
    assert _env_text(tmp_path).splitlines() == [f"{ENV_NAME}={FAKE_KEY}"]


def test_set_replaces_existing_key_and_keeps_other_lines(client, tmp_path):
    (tmp_path / ENV_FILE_NAME).write_text(f"# memo\nOTHER=1\n{ENV_NAME}=old-key-0000\nLAST=2\n", encoding="utf-8")

    client.put("/api/api-keys/openai", json={"key": FAKE_KEY})

    assert _env_text(tmp_path).splitlines() == ["# memo", "OTHER=1", f"{ENV_NAME}={FAKE_KEY}", "LAST=2"]


@pytest.mark.parametrize(
    "bad_key",
    [
        "",
        "   ",
        "short",
        "sk-abc def-0123456789",
        "sk-abcdef0123\nOTHER_SECRET=injected",
        "sk-abcdef0123'quoted'",
        'sk-abcdef0123"quoted"',
        "sk-abcdef0123=#$(whoami)",
        "ｓｋ－全角文字のキー０１２３",
        "x" * 501,
    ],
    ids=["empty", "blank", "short", "space", "newline", "single quote", "double quote", "shell", "fullwidth", "long"],
)
def test_set_rejects_unsafe_keys(client, tmp_path, bad_key):
    (tmp_path / ENV_FILE_NAME).write_text("OTHER=1\n", encoding="utf-8")

    response = client.put("/api/api-keys/openai", json={"key": bad_key})

    assert response.status_code == 400
    assert _env_text(tmp_path) == "OTHER=1\n", ".env は書き換わらない"
    assert os.environ[ENV_NAME] == ""
    if bad_key.strip():
        assert bad_key.strip() not in response.text, "エラー文に入力値を出さない"


def test_delete_removes_key(client, tmp_path):
    (tmp_path / ENV_FILE_NAME).write_text("OTHER=1\n", encoding="utf-8")
    client.put("/api/api-keys/openai", json={"key": FAKE_KEY})

    response = client.delete("/api/api-keys/openai")

    assert response.status_code == 200
    assert response.json()["configured"] is False and response.json()["hint"] is None
    assert _env_text(tmp_path).splitlines() == ["OTHER=1"]
    assert ENV_NAME not in os.environ
    assert not OpenAIProvider().is_configured()


def test_delete_when_nothing_is_registered(client, tmp_path):
    assert client.delete("/api/api-keys/openai").status_code == 200
    assert not (tmp_path / ENV_FILE_NAME).exists()


def test_unknown_provider(client):
    assert client.put("/api/api-keys/unknown", json={"key": FAKE_KEY}).status_code == 404
    assert client.delete("/api/api-keys/unknown").status_code == 404


def test_short_existing_key_shows_no_hint(client, monkeypatch):
    """短い値が環境変数に入っていても、末尾表示で全体が見えてしまわない。"""
    monkeypatch.setenv(ENV_NAME, "abc")
    status = client.get("/api/api-keys").json()[0]
    assert status["configured"] is True and status["hint"] is None


# ---------- ほかのサイトからの操作 ----------

EVIL_ORIGIN = "https://evil.example"


def test_cross_site_key_overwrite_is_rejected(client, tmp_path):
    response = client.put("/api/api-keys/openai", json={"key": FAKE_KEY}, headers={"Origin": EVIL_ORIGIN})

    assert response.status_code == 403
    assert _env_text(tmp_path) == "" and os.environ[ENV_NAME] == ""


def test_cross_site_transform_is_rejected_without_calling_provider(client, provider):
    """ほかのサイトのページから変換（課金）を起こせない。"""
    source = client.post("/api/images", files={"file": ("in.png", image_bytes(), "image/png")}).json()

    response = client.post(
        "/api/transforms",
        json={"input_image_id": source["id"], "prompt_body": "x"},
        headers={"Origin": EVIL_ORIGIN},
    )

    assert response.status_code == 403
    assert provider.calls == []


@pytest.mark.parametrize("origin", [EVIL_ORIGIN, "null", "http://127.0.0.1:9999", "http://localhost:8765"])
def test_other_origins_cannot_write(client, origin):
    for method, path in (("POST", "/api/genres"), ("DELETE", "/api/genres/1"), ("DELETE", "/api/api-keys/openai")):
        assert client.request(method, path, headers={"Origin": origin}).status_code == 403


def test_own_screen_can_write(client):
    response = client.put("/api/api-keys/openai", json={"key": FAKE_KEY}, headers={"Origin": BASE_URL})
    assert response.status_code == 200


def test_reads_are_not_blocked_by_origin(client):
    assert client.get("/api/genres", headers={"Origin": EVIL_ORIGIN}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8765", "192.168.1.10:8765"])
def test_unknown_host_names_are_rejected(client, host):
    """外部のドメイン名をこの PC に向けても、画面も API も返さない。"""
    assert client.get("/api/api-keys", headers={"Host": host}).status_code == 400
    assert client.get("/", headers={"Host": host}).status_code == 400


def test_localhost_name_is_accepted(tmp_path, provider):
    from fastapi.testclient import TestClient

    local = TestClient(make_client(tmp_path, provider).app, base_url="http://localhost:8765")
    assert local.get("/api/genres").status_code == 200
    assert local.post("/api/genres", json={"name": "a"}, headers={"Origin": "http://localhost:8765"}).status_code == 201


# ---------- 既定のプロバイダー（OpenAI・Grok・Gemini） ----------

def test_default_providers_are_listed_and_unusable_without_keys(tmp_path):
    """キーを登録していないプロバイダーは、一覧には出るが configured が false になる（画面で選べない）。"""
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.fakes import BASE_URL

    client = TestClient(create_app(data_dir=tmp_path, env_file=tmp_path / ".env"), base_url=BASE_URL)

    providers = client.get("/api/providers").json()
    assert [(item["name"], item["configured"], item["default"]) for item in providers] == [
        ("openai", False, True), ("grok", False, False), ("gemini", False, False),
    ]
    keys = client.get("/api/api-keys").json()
    assert [(item["provider"], item["env_name"]) for item in keys] == [
        ("openai", "OPENAI_API_KEY"), ("grok", "XAI_API_KEY"), ("gemini", "GEMINI_API_KEY"),
    ]

    # キーを登録したプロバイダーだけが使えるようになる
    assert client.put("/api/api-keys/gemini", json={"key": "dummy-key-for-test"}).status_code == 200
    configured = {item["name"]: item["configured"] for item in client.get("/api/providers").json()}
    assert configured == {"openai": False, "grok": False, "gemini": True}

    # キーのないプロバイダーを指定した変換は、API を呼ばずに断る
    image = client.post("/api/images", files={"file": ("a.png", image_bytes(), "image/png")}).json()
    response = client.post(
        "/api/transforms", json={"input_image_id": image["id"], "prompt_body": "x", "provider": "grok"}
    )
    assert response.status_code == 400
    assert client.get("/api/transforms").json() == []
