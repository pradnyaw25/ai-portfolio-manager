"""Publisher media path: upload the chart and attach it, degrade to text-only on failure."""

from src.social.twitter import TwitterPublisher

_CREDS = dict(api_key="k", api_secret="s", access_token="t", access_token_secret="ts", post_enabled=True)


class _Resp:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class _Session:
    """Fake session that handles both the multipart media upload and the JSON tweet."""

    def __init__(self, media_ok=True):
        self.media_ok = media_ok
        self.calls = []

    def post(self, url, headers=None, json=None, files=None, timeout=None):
        self.calls.append({"url": url, "json": json, "files": files})
        if "media/upload" in url:
            if not self.media_ok:
                return _Resp({}, status_code=403)
            return _Resp({"media_id_string": "MID123"})
        return _Resp({"data": {"id": "999"}})


def test_publish_uploads_and_attaches_media():
    session = _Session(media_ok=True)
    result = TwitterPublisher(**_CREDS, session=session).publish("chart tweet", media=b"\x89PNGdata")

    assert result.status == "posted"
    upload = next(c for c in session.calls if "media/upload" in c["url"])
    assert upload["files"] is not None  # the PNG was uploaded as multipart
    tweet = next(c for c in session.calls if c["url"].endswith("/2/tweets"))
    assert tweet["json"]["media"] == {"media_ids": ["MID123"]}


def test_publish_degrades_to_text_only_when_media_upload_fails():
    session = _Session(media_ok=False)
    result = TwitterPublisher(**_CREDS, session=session).publish("chart tweet", media=b"\x89PNGdata")

    assert result.status == "posted"  # the tweet still goes out
    tweet = next(c for c in session.calls if c["url"].endswith("/2/tweets"))
    assert "media" not in (tweet["json"] or {})  # no media attached


def test_publish_without_media_never_calls_upload():
    session = _Session()
    TwitterPublisher(**_CREDS, session=session).publish("plain tweet")

    assert not any("media/upload" in c["url"] for c in session.calls)
