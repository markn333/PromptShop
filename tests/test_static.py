"""画面のファイルの配信テスト。"""
import pytest


@pytest.mark.parametrize("path", ["/", "/static/app.js", "/static/style.css"])
def test_screen_files_are_revalidated_every_time(client, path):
    """ブラウザが古い画面のファイルを使い続けないよう、毎回確認させる指定が付いている。"""
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_unchanged_file_is_not_sent_again(client):
    first = client.get("/static/app.js")
    second = client.get("/static/app.js", headers={"If-None-Match": first.headers["etag"]})
    assert second.status_code == 304
    assert second.headers["cache-control"] == "no-cache"
