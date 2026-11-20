"""プロンプト API のテスト。"""
import pytest


def _genre(client, name):
    return client.post("/api/genres", json={"name": name}).json()


def _prompt(client, title, body, genre_id=None):
    response = client.post("/api/prompts", json={"title": title, "body": body, "genre_id": genre_id})
    assert response.status_code == 201
    return response.json()


def _titles(response):
    return [prompt["title"] for prompt in response.json()]


def test_create_and_get_back(client):
    genre = _genre(client, "画風変換")
    created = _prompt(client, "水彩", "水彩画風にする", genre["id"])

    assert created["title"] == "水彩"
    assert created["body"] == "水彩画風にする"
    assert created["genre_id"] == genre["id"]
    assert created["created_at"] == created["updated_at"]
    assert client.get("/api/prompts").json() == [created]


def test_create_without_genre_is_unclassified(client):
    assert _prompt(client, "水彩", "水彩画風にする")["genre_id"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "  ", "body": "本文"},
        {"title": "タイトル", "body": "  "},
        {"title": "タイトル"},
        {"body": "本文"},
        {"title": "x" * 101, "body": "本文"},
    ],
)
def test_create_rejects_invalid_input(client, payload):
    assert client.post("/api/prompts", json=payload).status_code == 422


def test_create_rejects_unknown_genre(client):
    response = client.post("/api/prompts", json={"title": "水彩", "body": "本文", "genre_id": 999})
    assert response.status_code == 400
    assert client.get("/api/prompts").json() == []


def test_duplicate_titles_are_allowed(client):
    _prompt(client, "水彩", "本文 1")
    _prompt(client, "水彩", "本文 2")
    assert len(client.get("/api/prompts").json()) == 2


def test_list_is_sorted_by_title(client):
    _prompt(client, "b-filter", "本文")
    _prompt(client, "A-filter", "本文")
    _prompt(client, "c-filter", "本文")
    assert _titles(client.get("/api/prompts")) == ["A-filter", "b-filter", "c-filter"]


def test_filter_by_genre_and_unclassified(client):
    style = _genre(client, "画風変換")
    color = _genre(client, "色調")
    _prompt(client, "水彩", "本文", style["id"])
    _prompt(client, "セピア", "本文", color["id"])
    _prompt(client, "メモ", "本文")

    assert _titles(client.get("/api/prompts", params={"genre_id": style["id"]})) == ["水彩"]
    assert _titles(client.get("/api/prompts", params={"genre_id": color["id"]})) == ["セピア"]
    assert _titles(client.get("/api/prompts", params={"unclassified": "true"})) == ["メモ"]


def test_search_matches_title_and_body(client):
    _prompt(client, "水彩", "やわらかい色でにじませる")
    _prompt(client, "油絵", "厚塗りの水彩ではない質感")
    _prompt(client, "モノクロ", "白黒にする")

    assert _titles(client.get("/api/prompts", params={"q": "水彩"})) == ["水彩", "油絵"]
    assert _titles(client.get("/api/prompts", params={"q": "白黒"})) == ["モノクロ"]
    assert _titles(client.get("/api/prompts", params={"q": "該当なし"})) == []


def test_search_treats_wildcards_literally(client):
    _prompt(client, "彩度 50% アップ", "本文")
    _prompt(client, "彩度 500 アップ", "本文")
    _prompt(client, "snake_case", "本文")
    _prompt(client, "snakeXcase", "本文")

    assert _titles(client.get("/api/prompts", params={"q": "50%"})) == ["彩度 50% アップ"]
    assert _titles(client.get("/api/prompts", params={"q": "snake_case"})) == ["snake_case"]


def test_search_combined_with_genre(client):
    style = _genre(client, "画風変換")
    _prompt(client, "水彩 A", "本文", style["id"])
    _prompt(client, "水彩 B", "本文")

    assert _titles(client.get("/api/prompts", params={"q": "水彩", "genre_id": style["id"]})) == ["水彩 A"]


def test_update(client):
    genre = _genre(client, "画風変換")
    prompt = _prompt(client, "水彩", "本文")

    response = client.put(
        f"/api/prompts/{prompt['id']}", json={"title": "水彩 改", "body": "新しい本文", "genre_id": genre["id"]}
    )

    assert response.status_code == 200
    updated = response.json()
    assert (updated["title"], updated["body"], updated["genre_id"]) == ("水彩 改", "新しい本文", genre["id"])
    assert updated["created_at"] == prompt["created_at"]


def test_update_can_clear_genre(client):
    genre = _genre(client, "画風変換")
    prompt = _prompt(client, "水彩", "本文", genre["id"])

    response = client.put(f"/api/prompts/{prompt['id']}", json={"title": "水彩", "body": "本文", "genre_id": None})

    assert response.json()["genre_id"] is None


def test_update_missing_prompt_returns_404(client):
    assert client.put("/api/prompts/999", json={"title": "x", "body": "y"}).status_code == 404


def test_update_rejects_unknown_genre(client):
    prompt = _prompt(client, "水彩", "本文")
    response = client.put(f"/api/prompts/{prompt['id']}", json={"title": "水彩", "body": "本文", "genre_id": 999})
    assert response.status_code == 400


def test_delete(client):
    prompt = _prompt(client, "水彩", "本文")
    assert client.delete(f"/api/prompts/{prompt['id']}").status_code == 204
    assert client.get("/api/prompts").json() == []


def test_delete_missing_prompt_returns_404(client):
    assert client.delete("/api/prompts/999").status_code == 404


def test_data_survives_restart(tmp_path, provider):
    """アプリを作り直しても、同じ保存先なら登録内容が残っている。"""
    from tests.fakes import make_client

    first = make_client(tmp_path, provider)
    _prompt(first, "水彩", "本文")

    second = make_client(tmp_path, provider)
    assert _titles(second.get("/api/prompts")) == ["水彩"]
