"""プロンプトの作例（変換結果を、プロンプトとプロバイダーの見本として登録する）のテスト。"""
import sqlite3

from app import config
from tests.fakes import FakeProvider, make_client, run_transform, upload


def _prompt(client, title="水彩"):
    return client.post("/api/prompts", json={"title": title, "body": f"{title}風にする"}).json()


def _examples(client, **params):
    return client.get("/api/images", params={"kind": "result", "example": "true", **params}).json()


def _ids(images):
    return [image["id"] for image in images]


def test_result_knows_its_prompt_and_provider(client):
    source = upload(client)
    prompt = _prompt(client)

    saved = run_transform(client, source["id"], prompt_id=prompt["id"])["output_image"]
    unsaved = run_transform(client, source["id"])["output_image"]

    assert (saved["prompt_id"], saved["provider"], saved["example"]) == (prompt["id"], "openai", False)
    assert saved["prompt_title"] == prompt["title"]
    assert (unsaved["prompt_id"], unsaved["provider"]) == (None, "openai")
    fetched = client.get(f"/api/images/{source['id']}").json()
    assert (fetched["prompt_id"], fetched["provider"], fetched["example"]) == (None, None, False)


def test_register_and_unregister_example(client):
    source = upload(client)
    prompt = _prompt(client)
    result = run_transform(client, source["id"], prompt_id=prompt["id"])["output_image"]
    url = f"/api/images/{result['id']}"

    registered = client.patch(url, json={"example": True})
    assert registered.status_code == 200 and registered.json()["example"] is True
    assert _ids(_examples(client, prompt_id=prompt["id"], provider="openai")) == [result["id"]]

    assert client.patch(url, json={"example": False}).json()["example"] is False
    assert _examples(client) == []


def test_example_is_independent_of_favorite_and_rating(client):
    source = upload(client)
    prompt = _prompt(client)
    result = run_transform(client, source["id"], prompt_id=prompt["id"])["output_image"]
    url = f"/api/images/{result['id']}"
    client.patch(url, json={"favorite": True, "rating": 4, "example": True})

    updated = client.patch(url, json={"favorite": False}).json()

    assert (updated["favorite"], updated["rating"], updated["example"]) == (False, 4, True)


def test_examples_are_listed_per_prompt_and_provider(client):
    source = upload(client)
    watercolor = _prompt(client, "水彩")
    sepia = _prompt(client, "セピア")
    first = run_transform(client, source["id"], prompt_id=watercolor["id"])["output_image"]
    second = run_transform(client, source["id"], prompt_id=watercolor["id"])["output_image"]
    not_example = run_transform(client, source["id"], prompt_id=watercolor["id"])["output_image"]
    other = run_transform(client, source["id"], prompt_id=sepia["id"])["output_image"]
    for image in (first, second, other):
        client.patch(f"/api/images/{image['id']}", json={"example": True})

    assert _ids(_examples(client, prompt_id=watercolor["id"], provider="openai")) == [second["id"], first["id"]]
    assert _ids(_examples(client, prompt_id=sepia["id"], provider="openai")) == [other["id"]]
    assert _examples(client, prompt_id=watercolor["id"], provider="gemini") == [], "別のプロバイダーの作例は出さない"
    assert not_example["id"] not in _ids(_examples(client))


def test_only_results_of_saved_prompts_can_be_examples(client):
    source = upload(client)
    unsaved = run_transform(client, source["id"])["output_image"]

    for image in (source, unsaved):
        response = client.patch(f"/api/images/{image['id']}", json={"example": True})
        assert response.status_code == 400 and "保存済みのプロンプト" in response.json()["detail"]
        assert client.get(f"/api/images/{image['id']}").json()["example"] is False
    assert client.patch(f"/api/images/{unsaved['id']}", json={"example": "yes"}).status_code == 422


def test_deleted_example_disappears(client):
    source = upload(client)
    prompt = _prompt(client)
    result = run_transform(client, source["id"], prompt_id=prompt["id"])["output_image"]
    client.patch(f"/api/images/{result['id']}", json={"example": True})

    client.delete(f"/api/images/{result['id']}")

    assert _examples(client, prompt_id=prompt["id"]) == []


def test_example_of_deleted_prompt_is_no_longer_listed_but_can_be_unregistered(client):
    source = upload(client)
    prompt = _prompt(client)
    result = run_transform(client, source["id"], prompt_id=prompt["id"])["output_image"]
    url = f"/api/images/{result['id']}"
    client.patch(url, json={"example": True})

    client.delete(f"/api/prompts/{prompt['id']}")

    assert _examples(client, prompt_id=prompt["id"]) == []
    orphan = client.get(url).json()
    assert orphan["example"] is True and orphan["prompt_id"] is None
    assert client.patch(url, json={"example": False}).json()["example"] is False
    assert client.patch(url, json={"example": True}).status_code == 400


def test_database_from_older_version_gets_the_new_column(tmp_path):
    """作例の列がない古いデータベースでも、起動時に列が足され、中身は残る。"""
    conn = sqlite3.connect(tmp_path / config.DB_FILE_NAME)
    with conn:
        conn.execute(
            "CREATE TABLE images (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, file_path TEXT NOT NULL,"
            " thumb_path TEXT, original_name TEXT, width INTEGER, height INTEGER,"
            " favorite INTEGER NOT NULL DEFAULT 0, rating INTEGER, deleted INTEGER NOT NULL DEFAULT 0,"
            " created_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO images (kind, file_path, original_name, favorite, rating, created_at)"
            " VALUES ('source', 'sources/old.png', 'old.png', 1, 5, '2026-11-01T00:00:00+00:00')"
        )
    conn.close()

    client = make_client(tmp_path, FakeProvider())
    # 2 回起動しても壊れない
    client = make_client(tmp_path, FakeProvider())

    images = client.get("/api/images").json()
    assert len(images) == 1
    kept = images[0]
    assert (kept["original_name"], kept["favorite"], kept["rating"], kept["example"]) == ("old.png", True, 5, False)
