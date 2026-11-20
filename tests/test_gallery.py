"""お気に入り・評価・削除・絞り込み・変換の連鎖のテスト。"""
import pytest

from app import config
from app.providers.base import TransformResult
from tests.fakes import FAKE_COST_USD, FAKE_MODEL, run_transform, upload


def _ids(images):
    return [image["id"] for image in images]


def _results(client, **params):
    return client.get("/api/images", params={"kind": "result", **params}).json()


# ---------- お気に入り・評価 ----------

def test_favorite_and_rating_are_independent(client):
    image = upload(client)
    url = f"/api/images/{image['id']}"

    assert client.patch(url, json={"favorite": True}).json()["favorite"] is True
    rated = client.patch(url, json={"rating": 4}).json()
    assert (rated["favorite"], rated["rating"]) == (True, 4), "評価を付けてもお気に入りは変わらない"

    unfavorited = client.patch(url, json={"favorite": False}).json()
    assert (unfavorited["favorite"], unfavorited["rating"]) == (False, 4), "お気に入りを外しても評価は残る"


def test_rating_can_be_cleared_with_null(client):
    image = upload(client)
    url = f"/api/images/{image['id']}"
    client.patch(url, json={"rating": 5})

    assert client.patch(url, json={"rating": None}).json()["rating"] is None
    assert client.get(url).json()["rating"] is None


def test_empty_patch_changes_nothing(client):
    image = upload(client)
    url = f"/api/images/{image['id']}"
    client.patch(url, json={"favorite": True, "rating": 3})

    unchanged = client.patch(url, json={}).json()

    assert (unchanged["favorite"], unchanged["rating"]) == (True, 3)


@pytest.mark.parametrize(
    "payload",
    [{"rating": 0}, {"rating": 6}, {"rating": "high"}, {"rating": 2.5}, {"favorite": "yes"}, {"favorite": 1}],
)
def test_patch_rejects_invalid_values(client, payload):
    image = upload(client)
    assert client.patch(f"/api/images/{image['id']}", json=payload).status_code == 422


def test_patch_missing_image(client):
    assert client.patch("/api/images/999", json={"favorite": True}).status_code == 404


# ---------- 削除 ----------

def test_delete_removes_files_but_keeps_history_and_cost(client, tmp_path):
    source = upload(client)
    transform = run_transform(client, source["id"])
    result = transform["output_image"]

    assert client.delete(f"/api/images/{result['id']}").status_code == 204

    assert list((tmp_path / config.RESULTS_DIR_NAME).iterdir()) == []
    assert len(list((tmp_path / config.THUMBS_DIR_NAME).iterdir())) == 1, "元画像のサムネイルだけが残る"
    assert client.get(f"/api/images/{result['id']}").status_code == 404
    assert client.get(result["file_url"]).status_code == 404
    assert client.get(result["thumb_url"]).status_code == 404
    assert _results(client) == []

    kept = client.get(f"/api/transforms/{transform['id']}").json()
    assert kept["status"] == "success" and kept["cost_usd"] == pytest.approx(FAKE_COST_USD)
    assert kept["output_image"]["deleted"] is True
    assert kept["output_image"]["file_url"] is None and kept["output_image"]["thumb_url"] is None
    assert client.get("/api/costs/summary").json()["total_usd"] == pytest.approx(FAKE_COST_USD)


def test_delete_twice_and_missing(client):
    image = upload(client)
    assert client.delete(f"/api/images/{image['id']}").status_code == 204
    assert client.delete(f"/api/images/{image['id']}").status_code == 404
    assert client.delete("/api/images/999").status_code == 404


def test_deleted_image_cannot_be_updated_or_transformed(client, provider):
    image = upload(client)
    client.delete(f"/api/images/{image['id']}")

    assert client.patch(f"/api/images/{image['id']}", json={"favorite": True}).status_code == 404
    response = client.post("/api/transforms", json={"input_image_id": image["id"], "prompt_body": "x"})
    assert response.status_code == 404
    assert provider.calls == [], "削除済みの画像では API を呼ばない"


def test_delete_succeeds_even_if_file_is_already_gone(client, tmp_path):
    image = upload(client)
    for path in (tmp_path / config.SOURCES_DIR_NAME).iterdir():
        path.unlink()

    assert client.delete(f"/api/images/{image['id']}").status_code == 204
    assert client.get("/api/images").json() == []


def test_delete_does_not_touch_files_outside_data_dir(client, tmp_path):
    """データベースのパスが保存先の外を指していても、そのファイルは消さない。"""
    import sqlite3

    image = upload(client)
    outside = tmp_path.parent / "keep.txt"
    outside.write_text("keep")
    conn = sqlite3.connect(tmp_path / config.DB_FILE_NAME)
    with conn:
        conn.execute("UPDATE images SET file_path = ? WHERE id = ?", ("../keep.txt", image["id"]))
    conn.close()

    assert client.delete(f"/api/images/{image['id']}").status_code == 204
    assert outside.read_text() == "keep"


# ---------- 絞り込み ----------

def test_filter_by_favorite_and_rating(client):
    source = upload(client)
    first = run_transform(client, source["id"])["output_image"]
    second = run_transform(client, source["id"])["output_image"]
    third = run_transform(client, source["id"])["output_image"]
    client.patch(f"/api/images/{first['id']}", json={"favorite": True, "rating": 2})
    client.patch(f"/api/images/{second['id']}", json={"rating": 4})

    assert _ids(_results(client)) == [third["id"], second["id"], first["id"]]
    assert _ids(_results(client, favorite="true")) == [first["id"]]
    assert _ids(_results(client, min_rating=2)) == [second["id"], first["id"]]
    assert _ids(_results(client, min_rating=3)) == [second["id"]]
    assert _results(client, min_rating=5) == []
    assert _results(client, favorite="true", min_rating=3) == []
    assert client.get("/api/images", params={"min_rating": 6}).status_code == 422


def test_filter_by_prompt_and_provider(client):
    source = upload(client)
    watercolor = client.post("/api/prompts", json={"title": "水彩", "body": "水彩画風にする"}).json()
    sepia = client.post("/api/prompts", json={"title": "セピア", "body": "セピア調にする"}).json()
    by_watercolor = run_transform(client, source["id"], prompt_id=watercolor["id"])["output_image"]
    by_sepia = run_transform(client, source["id"], prompt_id=sepia["id"])["output_image"]
    unsaved = run_transform(client, source["id"])["output_image"]

    assert _ids(_results(client, prompt_id=watercolor["id"])) == [by_watercolor["id"]]
    assert _ids(_results(client, prompt_id=sepia["id"])) == [by_sepia["id"]]
    assert _ids(_results(client, provider="openai")) == [unsaved["id"], by_sepia["id"], by_watercolor["id"]]
    assert _results(client, provider="gemini") == []
    # 取り込んだ元画像は、どの変換の出力でもないので当てはまらない
    assert client.get("/api/images", params={"kind": "source", "provider": "openai"}).json() == []


def test_list_limit(client):
    for _ in range(3):
        upload(client)

    assert len(client.get("/api/images", params={"limit": 2}).json()) == 2
    assert client.get("/api/images", params={"limit": 0}).status_code == 422
    assert client.get("/api/images", params={"limit": config.IMAGE_LIST_MAX_LIMIT + 1}).status_code == 422


# ---------- 変換の連鎖 ----------

def test_chain_of_source_image_has_no_steps(client):
    source = upload(client)

    chain = client.get(f"/api/images/{source['id']}/chain").json()

    assert chain["image"]["id"] == source["id"] and chain["steps"] == []


def test_chain_goes_back_to_first_source(client):
    source = upload(client)
    first = run_transform(client, source["id"], prompt_title="一段目")
    second = run_transform(client, first["output_image"]["id"], prompt_title="二段目")
    third = run_transform(client, second["output_image"]["id"], prompt_title="三段目")
    # 同じ元画像からの別の枝は、連鎖に混ざらない
    run_transform(client, source["id"], prompt_title="別の枝")

    chain = client.get(f"/api/images/{third['output_image']['id']}/chain").json()

    assert chain["image"]["id"] == third["output_image"]["id"]
    assert [step["prompt_title"] for step in chain["steps"]] == ["一段目", "二段目", "三段目"]
    assert chain["steps"][0]["input_image"]["id"] == source["id"]
    assert chain["steps"][0]["input_image"]["kind"] == "source"
    assert chain["steps"][1]["input_image"]["id"] == first["output_image"]["id"]
    assert chain["steps"][2]["model"] == FAKE_MODEL


def test_chain_survives_deleted_images_in_the_middle(client):
    source = upload(client)
    first = run_transform(client, source["id"], prompt_title="一段目")
    second = run_transform(client, first["output_image"]["id"], prompt_title="二段目")
    client.delete(f"/api/images/{source['id']}")
    client.delete(f"/api/images/{first['output_image']['id']}")

    chain = client.get(f"/api/images/{second['output_image']['id']}/chain").json()

    assert [step["prompt_title"] for step in chain["steps"]] == ["一段目", "二段目"]
    origin = chain["steps"][0]["input_image"]
    assert origin["deleted"] is True and origin["file_url"] is None
    assert chain["steps"][0]["output_image"]["deleted"] is True
    assert chain["steps"][1]["output_image"]["deleted"] is False


def test_chain_of_deleted_image_is_still_readable(client):
    source = upload(client)
    result = run_transform(client, source["id"])["output_image"]
    client.delete(f"/api/images/{result['id']}")

    chain = client.get(f"/api/images/{result['id']}/chain").json()

    assert chain["image"]["deleted"] is True and len(chain["steps"]) == 1


def test_chain_missing_image(client):
    assert client.get("/api/images/999/chain").status_code == 404


def test_failed_transform_is_not_part_of_any_chain(client, provider):
    source = upload(client)
    provider.result = TransformResult(model=FAKE_MODEL, error="拒否されました")
    run_transform(client, source["id"])

    assert client.get(f"/api/images/{source['id']}/chain").json()["steps"] == []
    assert _results(client) == []
