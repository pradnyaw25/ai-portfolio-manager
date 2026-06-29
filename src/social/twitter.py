import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import requests

from src.config import (
    DATA_DIR,
    POST_TWEET,
    X_ACCESS_TOKEN,
    X_ACCESS_TOKEN_SECRET,
    X_API_KEY,
    X_API_SECRET,
)

TWEET_CREATE_URL = "https://api.twitter.com/2/tweets"
SOCIAL_POSTS_FILE = DATA_DIR / "social_posts.jsonl"


@dataclass
class TweetPublishResult:
    status: str
    posted: bool
    dry_run: bool
    tweet_id: str | None = None
    text: str = ""
    error: str | None = None
    created_at: str | None = None
    run_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "posted": self.posted,
            "dry_run": self.dry_run,
            "tweet_id": self.tweet_id,
            "text": self.text,
            "error": self.error,
            "created_at": self.created_at,
            "run_id": self.run_id,
        }


class TwitterPublisher:
    def __init__(
        self,
        *,
        api_key: str = X_API_KEY,
        api_secret: str = X_API_SECRET,
        access_token: str = X_ACCESS_TOKEN,
        access_token_secret: str = X_ACCESS_TOKEN_SECRET,
        post_enabled: bool = POST_TWEET,
        session: requests.Session | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        self.access_token_secret = access_token_secret
        self.post_enabled = post_enabled
        self.session = session or requests.Session()

    def publish(self, text: str, *, run_id: str | None = None) -> TweetPublishResult:
        text = text.strip()[:280]
        created_at = _utc_now()

        if not text:
            return TweetPublishResult(
                status="skipped",
                posted=False,
                dry_run=not self.post_enabled,
                text=text,
                error="empty tweet text",
                created_at=created_at,
                run_id=run_id,
            )

        if not self.post_enabled:
            return TweetPublishResult(
                status="dry_run",
                posted=False,
                dry_run=True,
                text=text,
                created_at=created_at,
                run_id=run_id,
            )

        missing = self._missing_credentials()
        if missing:
            return TweetPublishResult(
                status="missing_credentials",
                posted=False,
                dry_run=False,
                text=text,
                error=f"Missing X credentials: {', '.join(missing)}",
                created_at=created_at,
                run_id=run_id,
            )

        payload = {"text": text}
        headers = {
            "Authorization": self._authorization_header(
                method="POST",
                url=TWEET_CREATE_URL,
            ),
            "Content-Type": "application/json",
        }

        try:
            response = self.session.post(
                TWEET_CREATE_URL,
                headers=headers,
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            return TweetPublishResult(
                status="error",
                posted=False,
                dry_run=False,
                text=text,
                error=str(exc),
                created_at=created_at,
                run_id=run_id,
            )

        tweet_id = (body.get("data") or {}).get("id")
        return TweetPublishResult(
            status="posted",
            posted=True,
            dry_run=False,
            tweet_id=tweet_id,
            text=text,
            created_at=created_at,
            run_id=run_id,
        )

    def _missing_credentials(self) -> list[str]:
        missing = []
        for name, value in [
            ("X_API_KEY", self.api_key),
            ("X_API_SECRET", self.api_secret),
            ("X_ACCESS_TOKEN", self.access_token),
            ("X_ACCESS_TOKEN_SECRET", self.access_token_secret),
        ]:
            if not value:
                missing.append(name)
        return missing

    def _authorization_header(self, *, method: str, url: str) -> str:
        oauth_params = {
            "oauth_consumer_key": self.api_key,
            "oauth_nonce": uuid.uuid4().hex,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_token": self.access_token,
            "oauth_version": "1.0",
        }
        signature = _oauth_signature(
            method=method,
            url=url,
            params=oauth_params,
            api_secret=self.api_secret,
            access_token_secret=self.access_token_secret,
        )
        oauth_params["oauth_signature"] = signature
        return "OAuth " + ", ".join(
            f'{_percent_encode(key)}="{_percent_encode(value)}"'
            for key, value in sorted(oauth_params.items())
        )


def publish_tweet(text: str, *, run_id: str | None = None) -> TweetPublishResult:
    result = TwitterPublisher().publish(text, run_id=run_id)
    append_social_post(result)
    return result


def append_social_post(result: TweetPublishResult, path: Path = SOCIAL_POSTS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(result.to_dict()) + "\n")


def _oauth_signature(
    *,
    method: str,
    url: str,
    params: dict[str, str],
    api_secret: str,
    access_token_secret: str,
) -> str:
    normalized_params = "&".join(
        f"{_percent_encode(key)}={_percent_encode(value)}"
        for key, value in sorted(params.items())
    )
    signature_base = "&".join(
        [
            method.upper(),
            _percent_encode(url),
            _percent_encode(normalized_params),
        ]
    )
    signing_key = f"{_percent_encode(api_secret)}&{_percent_encode(access_token_secret)}"
    digest = hmac.new(
        signing_key.encode("utf-8"),
        signature_base.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def _percent_encode(value: str) -> str:
    return quote(str(value), safe="~-._")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
