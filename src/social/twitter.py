import base64
import hashlib
import hmac
import json
import re
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
from src.utils.logger import get_logger

logger = get_logger(__name__)

TWEET_CREATE_URL = "https://api.twitter.com/2/tweets"
MEDIA_UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"
SOCIAL_POSTS_FILE = DATA_DIR / "social_posts.jsonl"


@dataclass
class TweetPublishResult:
    status: str
    posted: bool
    dry_run: bool
    tweet_id: str | None = None
    tweet_url: str | None = None
    text: str = ""
    error: str | None = None
    error_code: str | None = None
    http_status: int | None = None
    created_at: str | None = None
    run_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "posted": self.posted,
            "dry_run": self.dry_run,
            "tweet_id": self.tweet_id,
            "tweet_url": self.tweet_url,
            "text": self.text,
            "error": self.error,
            "error_code": self.error_code,
            "http_status": self.http_status,
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

    def publish(
        self, text: str, *, media: bytes | None = None, run_id: str | None = None
    ) -> TweetPublishResult:
        text = sanitize_tweet_for_x(text.strip())[:280]
        created_at = _utc_now()

        if not text:
            return TweetPublishResult(
                status="skipped",
                posted=False,
                dry_run=not self.post_enabled,
                text=text,
                error="empty tweet text",
                error_code="empty_text",
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
                error_code="missing_credentials",
                created_at=created_at,
                run_id=run_id,
            )

        payload = {"text": text}
        if media is not None:
            media_id = self._upload_media(media)
            if media_id:
                payload["media"] = {"media_ids": [media_id]}
            # If upload fails, degrade to a text-only tweet rather than dropping it.

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
        except requests.HTTPError as exc:
            response = exc.response
            http_status = response.status_code if response is not None else None
            return TweetPublishResult(
                status="error",
                posted=False,
                dry_run=False,
                text=text,
                error=str(exc),
                error_code=f"http_{http_status}" if http_status else "http_error",
                http_status=http_status,
                created_at=created_at,
                run_id=run_id,
            )
        except Exception as exc:
            return TweetPublishResult(
                status="error",
                posted=False,
                dry_run=False,
                text=text,
                error=str(exc),
                error_code=f"exception_{type(exc).__name__}",
                created_at=created_at,
                run_id=run_id,
            )

        tweet_id = (body.get("data") or {}).get("id")
        return TweetPublishResult(
            status="posted",
            posted=True,
            dry_run=False,
            tweet_id=tweet_id,
            tweet_url=tweet_url(tweet_id),
            text=text,
            created_at=created_at,
            run_id=run_id,
        )

    def _upload_media(self, image: bytes) -> str | None:
        """Upload a PNG via the v1.1 media endpoint (multipart — its body is excluded
        from the OAuth signature, so the standard header signing applies). Returns the
        media id, or None on failure so publishing can fall back to text-only."""
        try:
            headers = {"Authorization": self._authorization_header(method="POST", url=MEDIA_UPLOAD_URL)}
            response = self.session.post(
                MEDIA_UPLOAD_URL,
                headers=headers,
                files={"media": ("chart.png", image, "image/png")},
                timeout=60,
            )
            response.raise_for_status()
            media_id = (response.json() or {}).get("media_id_string")
            if not media_id:
                logger.warning("Media upload returned no media_id_string")
            return media_id
        except Exception as exc:
            logger.warning("Media upload failed — posting text-only: %s", exc)
            return None

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


def publish_tweet(
    text: str, *, media: bytes | None = None, run_id: str | None = None, dry_run: bool = False
) -> TweetPublishResult:
    # dry_run forces posting off regardless of POST_TWEET — an explicit kill switch,
    # so a test can never publish by accident (see docs/incidents.md 2026-07-06).
    publisher = TwitterPublisher(post_enabled=False) if dry_run else TwitterPublisher()
    result = publisher.publish(text, media=media, run_id=run_id)
    append_social_post(result)
    return result


_CASHTAG_RE = re.compile(r"\$([A-Za-z]{1,6}(?:\.[A-Za-z]{1,2})?)\b")


def sanitize_tweet_for_x(text: str) -> str:
    """Keep a single cashtag, but strip cashtags when two or more distinct symbols are
    tagged. One ``$TICKER`` surfaces a single-name tweet in that symbol's feed; several
    cashtags read as spam and X throttles them. The generator adds at most one cashtag
    (``TweetGeneratorAgent._apply_cashtag``); this is the defensive backstop for any
    other source of tweet text."""
    distinct = {m.group(1).upper() for m in _CASHTAG_RE.finditer(text)}
    if len(distinct) <= 1:
        return text
    return _CASHTAG_RE.sub(r"\1", text)


def append_social_post(result: TweetPublishResult, path: Path = SOCIAL_POSTS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(result.to_dict()) + "\n")


def tweet_url(tweet_id: str | None) -> str | None:
    if not tweet_id:
        return None
    return f"https://x.com/i/web/status/{tweet_id}"


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
