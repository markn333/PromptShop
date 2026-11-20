"""画像 API のテスト。"""
import io

import pytest
from PIL import Image

from app import config
from tests.fakes import image_bytes


def _upload(client, data, filename="photo.png"):
    return client.post("/api/images", files={"file": (filename, data, "application/octet-stream")})


@pytest.mark.parametrize("image_format", ["PNG", "JPEG", "WEBP"])
def test_upload_accepts_supported_formats(client, image_format):
    response = _upload(client, image_bytes(image_format, size=(64, 48)))

    assert response.status_code == 201
    image = response.json()
    assert (image["kind"], image["width"], image["height"]) == ("source", 64, 48)
    assert image["original_name"] == "photo.png"
    assert image["favorite"] is False and image["rating"] is None and image["deleted"] is False


def test_upload_returns_no_file_path(client):
    image = _upload(client, image_bytes()).json()
    assert "file_path" not in image and "thumb_path" not in image


def test_uploaded_file_is_served_unchanged(client):
    data = image_bytes("JPEG")
    image = _upload(client, data, "a.jpg").json()

    response = client.get(image["file_url"])

    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"] == "image/jpeg"


def test_thumbnail_is_small_jpeg(client):
    image = _upload(client, image_bytes(size=(1600, 800))).json()

    response = client.get(image["thumb_url"])

    thumb = Image.open(io.BytesIO(response.content))
    assert thumb.format == "JPEG"
    assert thumb.size == (config.THUMB_MAX_PX, config.THUMB_MAX_PX // 2)


def test_thumbnail_of_transparent_png(client):
    buffer = io.BytesIO()
    Image.new("RGBA", (40, 40), (0, 0, 0, 0)).save(buffer, format="PNG")
    image = _upload(client, buffer.getvalue()).json()

    thumb = Image.open(io.BytesIO(client.get(image["thumb_url"]).content))

    assert thumb.convert("RGB").getpixel((5, 5)) == (255, 255, 255)


@pytest.mark.parametrize(
    "data",
    [b"this is not an image", b"", image_bytes("GIF"), image_bytes("BMP"), image_bytes()[:40]],
    ids=["text", "empty", "gif", "bmp", "truncated"],
)
def test_upload_rejects_invalid_files(client, tmp_path, data):
    response = _upload(client, data)

    assert response.status_code == 400
    assert client.get("/api/images").json() == []
    # 断ったファイルを保存先に残さない
    assert list((tmp_path / config.SOURCES_DIR_NAME).iterdir()) == []
    assert list((tmp_path / config.THUMBS_DIR_NAME).iterdir()) == []


def test_upload_ignores_extension_and_checks_content(client):
    assert _upload(client, b"MZ fake exe", "evil.png").status_code == 400


def test_upload_rejects_too_large_file(client, monkeypatch):
    data = image_bytes()
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", len(data) - 1)
    assert _upload(client, data).status_code == 413


def test_upload_file_name_is_not_used_as_path(client, tmp_path):
    image = _upload(client, image_bytes(), "../../evil.png").json()

    assert image["original_name"] == "evil.png"
    saved = [path.name for path in (tmp_path / config.SOURCES_DIR_NAME).iterdir()]
    assert len(saved) == 1 and saved[0].startswith("source_") and "evil" not in saved[0]
    assert not (tmp_path.parent / "evil.png").exists()


def test_list_is_newest_first_and_filters_by_kind(client):
    first = _upload(client, image_bytes(), "1.png").json()
    second = _upload(client, image_bytes(), "2.png").json()

    assert [image["id"] for image in client.get("/api/images").json()] == [second["id"], first["id"]]
    assert len(client.get("/api/images", params={"kind": "source"}).json()) == 2
    assert client.get("/api/images", params={"kind": "result"}).json() == []
    assert client.get("/api/images", params={"kind": "other"}).status_code == 422


def test_get_image_and_missing(client):
    image = _upload(client, image_bytes()).json()

    assert client.get(f"/api/images/{image['id']}").json() == image
    assert client.get("/api/images/999").status_code == 404
    assert client.get("/api/images/999/file").status_code == 404
    assert client.get("/api/images/999/thumb").status_code == 404


def test_tampered_path_outside_data_dir_is_not_served(client, tmp_path):
    """データベースのパスが保存先の外を指していても、そのファイルは返さない。"""
    import sqlite3

    image = _upload(client, image_bytes()).json()
    secret = tmp_path.parent / "secret.txt"
    secret.write_text("secret")
    conn = sqlite3.connect(tmp_path / config.DB_FILE_NAME)
    with conn:
        conn.execute("UPDATE images SET file_path = ? WHERE id = ?", ("../secret.txt", image["id"]))
    conn.close()

    assert client.get(image["file_url"]).status_code == 404
