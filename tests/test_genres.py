"""ジャンル API のテスト。"""


def _create(client, name):
    response = client.post("/api/genres", json={"name": name})
    assert response.status_code == 201
    return response.json()


def test_list_is_empty_at_first(client):
    assert client.get("/api/genres").json() == []


def test_create_appends_in_order(client):
    first = _create(client, "画風変換")
    second = _create(client, "フィルター")

    names = [genre["name"] for genre in client.get("/api/genres").json()]
    assert names == ["画風変換", "フィルター"]
    assert first["sort_order"] < second["sort_order"]


def test_create_strips_whitespace(client):
    assert _create(client, "  画風変換  ")["name"] == "画風変換"


def test_create_rejects_blank_name(client):
    assert client.post("/api/genres", json={"name": "   "}).status_code == 422


def test_create_rejects_duplicate_name(client):
    _create(client, "画風変換")
    response = client.post("/api/genres", json={"name": "画風変換"})
    assert response.status_code == 409
    assert "画風変換" in response.json()["detail"]


def test_rename(client):
    genre = _create(client, "画風変換")
    response = client.put(f"/api/genres/{genre['id']}", json={"name": "画風"})
    assert response.status_code == 200
    assert response.json()["name"] == "画風"
    assert response.json()["sort_order"] == genre["sort_order"]


def test_rename_to_existing_name_is_rejected(client):
    _create(client, "画風変換")
    other = _create(client, "フィルター")
    response = client.put(f"/api/genres/{other['id']}", json={"name": "画風変換"})
    assert response.status_code == 409


def test_change_sort_order(client):
    first = _create(client, "画風変換")
    second = _create(client, "フィルター")
    client.put(f"/api/genres/{second['id']}", json={"sort_order": 0})
    client.put(f"/api/genres/{first['id']}", json={"sort_order": 1})

    names = [genre["name"] for genre in client.get("/api/genres").json()]
    assert names == ["フィルター", "画風変換"]


def test_update_missing_genre_returns_404(client):
    assert client.put("/api/genres/999", json={"name": "x"}).status_code == 404


def test_delete(client):
    genre = _create(client, "画風変換")
    assert client.delete(f"/api/genres/{genre['id']}").status_code == 204
    assert client.get("/api/genres").json() == []


def test_delete_missing_genre_returns_404(client):
    assert client.delete("/api/genres/999").status_code == 404


def test_delete_makes_prompts_unclassified(client):
    genre = _create(client, "画風変換")
    prompt = client.post(
        "/api/prompts", json={"title": "水彩", "body": "水彩画風にする", "genre_id": genre["id"]}
    ).json()

    client.delete(f"/api/genres/{genre['id']}")

    remaining = client.get("/api/prompts").json()
    assert [item["id"] for item in remaining] == [prompt["id"]]
    assert remaining[0]["genre_id"] is None
