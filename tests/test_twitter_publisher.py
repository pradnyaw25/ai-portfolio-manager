import json

from src.reporting import public_exporter
from src.reporting.public_exporter import PublicExporter
from src.social.twitter import TwitterPublisher, append_social_post, sanitize_tweet_for_x


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def post(self, url, headers, json, timeout):
        self.requests.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return self.response


def test_twitter_publisher_dry_run_when_disabled():
    result = TwitterPublisher(post_enabled=False).publish("hello world", run_id="run_1")

    assert result.status == "dry_run"
    assert not result.posted
    assert result.dry_run
    assert result.text == "hello world"
    assert result.run_id == "run_1"


def test_twitter_publisher_reports_missing_credentials_when_enabled():
    result = TwitterPublisher(
        api_key="",
        api_secret="",
        access_token="",
        access_token_secret="",
        post_enabled=True,
    ).publish("hello world")

    assert result.status == "missing_credentials"
    assert not result.posted
    assert "X_API_KEY" in result.error
    assert "X_ACCESS_TOKEN_SECRET" in result.error


def test_twitter_publisher_posts_with_oauth_header():
    session = FakeSession(FakeResponse({"data": {"id": "tweet_123"}}))
    publisher = TwitterPublisher(
        api_key="api_key",
        api_secret="api_secret",
        access_token="access_token",
        access_token_secret="access_secret",
        post_enabled=True,
        session=session,
    )

    result = publisher.publish("portfolio update", run_id="run_1")

    assert result.status == "posted"
    assert result.posted
    assert result.tweet_id == "tweet_123"
    assert session.requests[0]["json"] == {"text": "portfolio update"}
    assert session.requests[0]["headers"]["Authorization"].startswith("OAuth ")


def test_twitter_publisher_removes_all_cashtags_before_posting():
    session = FakeSession(FakeResponse({"data": {"id": "tweet_123"}}))
    publisher = TwitterPublisher(
        api_key="api_key",
        api_secret="api_secret",
        access_token="access_token",
        access_token_secret="access_secret",
        post_enabled=True,
        session=session,
    )

    result = publisher.publish("Trades: SELL $AAPL, SELL $NVDA, BUY $PG")

    assert result.text == "Trades: SELL AAPL, SELL NVDA, BUY PG"
    assert session.requests[0]["json"] == {"text": "Trades: SELL AAPL, SELL NVDA, BUY PG"}


def test_sanitize_tweet_for_x_removes_all_cashtags():
    assert (
        sanitize_tweet_for_x("SELL $AAPL, SELL $NVDA, BUY $PG")
        == "SELL AAPL, SELL NVDA, BUY PG"
    )


def test_append_social_post_writes_jsonl(tmp_path):
    result = TwitterPublisher(post_enabled=False).publish("hello", run_id="run_1")
    path = tmp_path / "social_posts.jsonl"

    append_social_post(result, path=path)

    payload = json.loads(path.read_text().strip())
    assert payload["status"] == "dry_run"
    assert payload["run_id"] == "run_1"


def test_public_exporter_updates_latest_tweet_publish_status(tmp_path, monkeypatch):
    monkeypatch.setattr(public_exporter, "PUBLIC_DIR", tmp_path)
    (tmp_path / "latest_tweet.json").write_text(
        json.dumps(
            {
                "run_id": "run_1",
                "text": "hello",
                "posted": False,
            }
        )
    )

    PublicExporter().update_latest_tweet_status(
        {
            "status": "posted",
            "posted": True,
            "tweet_id": "tweet_123",
            "error": None,
            "created_at": "2026-06-28T12:00:00Z",
        }
    )

    payload = json.loads((tmp_path / "latest_tweet.json").read_text())
    assert payload["posted"]
    assert payload["publish_status"] == "posted"
    assert payload["tweet_id"] == "tweet_123"
    assert payload["published_at"] == "2026-06-28T12:00:00Z"
