"""変換 API のテスト。偽プロバイダーを使い、実際の API は呼ばない。"""
import threading

import pytest

from app import config
from app.providers.base import TransformResult
from tests.fakes import FAKE_COST_USD, FAKE_MODEL, image_bytes


def _upload(client):
    return client.post("/api/images", files={"file": ("in.png", image_bytes(), "image/png")}).json()


def _prompt(client, title="水彩", body="水彩画風にする"):
    return client.post("/api/prompts", json={"title": title, "body": body}).json()


def _run(client, image_id, **overrides):
    payload = {"input_image_id": image_id, "prompt_body": "水彩画風にする", "prompt_title": "水彩"}
    payload.update(overrides)
    return client.post("/api/transforms", json=payload)


def test_success_records_history_and_saves_output(client, provider):
    source = _upload(client)
    prompt = _prompt(client)

    response = _run(client, source["id"], prompt_id=prompt["id"])

    assert response.status_code == 201
    transform = response.json()
    assert transform["status"] == "success" and transform["error_message"] is None
    assert (transform["provider"], transform["model"]) == ("openai", FAKE_MODEL)
    assert transform["cost_usd"] == pytest.approx(FAKE_COST_USD)
    assert (transform["prompt_id"], transform["prompt_title"]) == (prompt["id"], "水彩")
    assert transform["input_image"]["id"] == source["id"]
    assert transform["output_image"]["kind"] == "result"
    assert client.get(transform["output_image"]["file_url"]).content == provider.result.image_bytes
    assert len(provider.calls) == 1


def test_provider_receives_input_file_and_prompt(client, provider):
    source = _upload(client)

    _run(client, source["id"], prompt_body="  セピア調にする  ")

    path, prompt = provider.calls[0]
    assert path.read_bytes() == client.get(source["file_url"]).content
    assert prompt == "セピア調にする"


def test_original_image_is_not_modified(client):
    source = _upload(client)
    before = client.get(source["file_url"]).content

    _run(client, source["id"])

    assert client.get(source["file_url"]).content == before


def test_history_keeps_body_as_executed(client):
    """本文を一時的に書き換えて実行し、その後プロンプトを編集・削除しても、履歴は実行時点のまま。"""
    source = _upload(client)
    prompt = _prompt(client, body="保存済みの本文")
    transform = _run(client, source["id"], prompt_id=prompt["id"], prompt_body="その場で書き換えた本文").json()

    client.put(f"/api/prompts/{prompt['id']}", json={"title": "改名", "body": "編集後の本文"})
    edited = client.get(f"/api/transforms/{transform['id']}").json()
    assert (edited["prompt_title"], edited["prompt_body"]) == ("水彩", "その場で書き換えた本文")
    assert edited["prompt_id"] == prompt["id"]

    client.delete(f"/api/prompts/{prompt['id']}")
    orphaned = client.get(f"/api/transforms/{transform['id']}").json()
    assert (orphaned["prompt_title"], orphaned["prompt_body"]) == ("水彩", "その場で書き換えた本文")
    assert orphaned["prompt_id"] is None


def test_unsaved_prompt_gets_default_title(client):
    source = _upload(client)
    response = client.post("/api/transforms", json={"input_image_id": source["id"], "prompt_body": "白黒にする"})

    transform = response.json()
    assert transform["prompt_title"] == config.UNSAVED_PROMPT_TITLE
    assert transform["prompt_id"] is None


def test_result_can_be_used_as_input_again(client, provider):
    source = _upload(client)
    first = _run(client, source["id"]).json()

    second = _run(client, first["output_image"]["id"]).json()

    assert second["status"] == "success"
    assert second["input_image"]["id"] == first["output_image"]["id"]
    assert len(provider.calls) == 2


def test_failure_is_recorded_without_output(client, provider):
    provider.result = TransformResult(model=FAKE_MODEL, error="コンテンツポリシーにより拒否されました")
    source = _upload(client)

    response = _run(client, source["id"])

    assert response.status_code == 201
    transform = response.json()
    assert transform["status"] == "failed"
    assert transform["error_message"] == "コンテンツポリシーにより拒否されました"
    assert transform["output_image"] is None and transform["cost_usd"] == 0
    assert client.get("/api/images", params={"kind": "result"}).json() == []
    assert len(provider.calls) == 1, "失敗しても自動で再試行しない"


def test_billed_failure_keeps_cost(client, provider):
    provider.result = TransformResult(model=FAKE_MODEL, error="出力がブロックされました", cost_usd=0.04,
                                      billed_on_failure=True)
    source = _upload(client)

    transform = _run(client, source["id"]).json()

    assert transform["status"] == "failed" and transform["cost_usd"] == pytest.approx(0.04)


def test_provider_exception_becomes_failed_history(client, provider):
    provider.raises = RuntimeError("boom sk-secret-key")
    source = _upload(client)

    response = _run(client, source["id"])

    transform = response.json()
    assert response.status_code == 201 and transform["status"] == "failed"
    assert "RuntimeError" in transform["error_message"]
    assert "sk-secret-key" not in transform["error_message"]


def test_non_image_output_becomes_failed_history_with_cost(client, provider):
    provider.result = TransformResult(model=FAKE_MODEL, image_bytes=b"not an image", cost_usd=FAKE_COST_USD)
    source = _upload(client)

    transform = _run(client, source["id"]).json()

    assert transform["status"] == "failed" and transform["output_image"] is None
    assert transform["cost_usd"] == pytest.approx(FAKE_COST_USD)


@pytest.mark.parametrize(
    ("overrides", "expected_status"),
    [
        ({"input_image_id": 999}, 404),
        ({"prompt_id": 999}, 404),
        ({"provider": "unknown"}, 400),
        ({"prompt_body": "   "}, 422),
    ],
    ids=["missing image", "missing prompt", "unknown provider", "blank body"],
)
def test_invalid_request_does_not_call_provider(client, provider, overrides, expected_status):
    source = _upload(client)

    response = _run(client, **{"image_id": source["id"], **overrides}) if "input_image_id" not in overrides \
        else client.post("/api/transforms", json={"prompt_body": "x", **overrides})

    assert response.status_code == expected_status
    assert provider.calls == []
    assert client.get("/api/transforms").json() == []


def test_unconfigured_provider_is_rejected_before_calling(client, provider):
    provider.configured = False
    source = _upload(client)

    response = _run(client, source["id"])

    assert response.status_code == 400
    assert "API キー" in response.json()["detail"]
    assert provider.calls == []


def test_second_request_while_running_is_rejected(client, provider):
    source = _upload(client)
    provider.release = threading.Event()
    results = []
    worker = threading.Thread(target=lambda: results.append(_run(client, source["id"])))
    worker.start()
    assert provider.entered.wait(timeout=5)

    busy = _run(client, source["id"])

    provider.release.set()
    worker.join(timeout=10)
    assert busy.status_code == 409
    assert results[0].status_code == 201
    assert len(provider.calls) == 1
    # 実行が終われば、次の変換は受け付ける
    assert _run(client, source["id"]).status_code == 201


def test_list_filters(client, provider):
    first_source = _upload(client)
    second_source = _upload(client)
    prompt = _prompt(client)
    ok = _run(client, first_source["id"], prompt_id=prompt["id"]).json()
    provider.result = TransformResult(model=FAKE_MODEL, error="失敗")
    ng = _run(client, second_source["id"]).json()

    def ids(**params):
        return [item["id"] for item in client.get("/api/transforms", params=params).json()]

    assert ids() == [ng["id"], ok["id"]]
    assert ids(input_image_id=first_source["id"]) == [ok["id"]]
    assert ids(prompt_id=prompt["id"]) == [ok["id"]]
    assert ids(status="failed") == [ng["id"]]
    assert ids(status="success") == [ok["id"]]
    assert client.get("/api/transforms/999").status_code == 404


def test_providers_endpoint(client, provider):
    assert client.get("/api/providers").json() == [
        {"name": "openai", "label": "Fake", "model": FAKE_MODEL, "configured": True, "default": True}
    ]
    provider.configured = False
    assert client.get("/api/providers").json()[0]["configured"] is False


def test_keep_aspect_is_on_by_default_and_passed_to_provider(client, provider):
    image = _upload(client)

    _run(client, image["id"])
    _run(client, image["id"], keep_aspect=False)

    assert provider.keep_aspect_calls == [True, False]


def test_keep_aspect_must_be_boolean(client, provider):
    image = _upload(client)

    response = client.post(
        "/api/transforms", json={"input_image_id": image["id"], "prompt_body": "x", "keep_aspect": "no"}
    )

    assert response.status_code == 422 and provider.calls == []
