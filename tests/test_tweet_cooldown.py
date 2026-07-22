from datetime import UTC, datetime

from src.social.cooldown import _symbols_in, load_recent_posts, recent_tweet_symbols

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


def _post(created_at, text, status="posted"):
    return {"status": status, "created_at": created_at, "text": text}


def test_symbols_in_matches_bare_and_cashtag_whole_words():
    universe = {"AAPL", "NVDA", "MA", "V"}
    found = _symbols_in("Boldest call: AAPL to beat SPY, watching $NVDA and MA.", universe)
    assert found == {"AAPL", "NVDA", "MA"}
    # Must not match inside a longer token.
    assert _symbols_in("AVGO strength", {"V"}) == set()


def test_recent_only_counts_posts_inside_the_window():
    posts = [
        _post("2026-07-21T15:00:00Z", "AAPL to outperform"),   # 1d ago → in
        _post("2026-07-10T15:00:00Z", "NVDA lagging"),         # 12d ago → out
    ]
    assert recent_tweet_symbols(posts, within_days=3, now=NOW) == {"AAPL"}


def test_recent_ignores_posts_that_never_reached_the_feed():
    posts = [
        _post("2026-07-22T09:00:00Z", "PG defensive", status="error"),
        _post("2026-07-22T09:00:00Z", "HD steady", status="blocked_grounding"),
        _post("2026-07-22T09:00:00Z", "MU cycle", status="dry_run"),  # dry_run counts
    ]
    assert recent_tweet_symbols(posts, within_days=3, now=NOW) == {"MU"}


def test_recent_handles_unparseable_or_missing_timestamps():
    posts = [_post(None, "AAPL"), _post("garbage", "NVDA")]
    assert recent_tweet_symbols(posts, within_days=3, now=NOW) == set()


def test_load_recent_posts_reads_jsonl_and_skips_bad_lines(tmp_path):
    path = tmp_path / "social_posts.jsonl"
    path.write_text('{"status":"posted","text":"AAPL"}\nnot-json\n{"status":"posted","text":"NVDA"}\n')
    posts = load_recent_posts(path)
    assert [p["text"] for p in posts] == ["AAPL", "NVDA"]


def test_load_recent_posts_missing_file_is_empty(tmp_path):
    assert load_recent_posts(tmp_path / "nope.jsonl") == []
