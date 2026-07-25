import pytest

from src.social.eng_content import (
    ENGINEERING_URL,
    load_notes,
    render_note_tweet,
    select_note,
)


def _note(note_id, text):
    return {"id": note_id, "topic": "t", "text": text}


def _post(created_at, text, status="posted"):
    return {"status": status, "created_at": created_at, "text": text}


# --- the shipped pool ------------------------------------------------------------


def test_shipped_pool_loads_with_unique_ids():
    notes = load_notes()
    assert len(notes) >= 8
    ids = [n["id"] for n in notes]
    assert len(ids) == len(set(ids))


def test_every_shipped_note_fits_the_tweet_limit():
    for note in load_notes():
        tweet = render_note_tweet(note)
        assert len(tweet) <= 280, f"{note['id']} is {len(tweet)} chars"
        assert tweet.endswith(ENGINEERING_URL)


def test_load_notes_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "notes.yaml"
    path.write_text("notes:\n  - {id: a, text: one}\n  - {id: a, text: two}\n")
    with pytest.raises(ValueError):
        load_notes(path)


def test_load_notes_skips_entries_without_id_or_text(tmp_path):
    path = tmp_path / "notes.yaml"
    path.write_text("notes:\n  - {id: good, text: real}\n  - {text: no-id}\n  - {id: no-text}\n")
    assert [n["id"] for n in load_notes(path)] == ["good"]


# --- rendering -------------------------------------------------------------------


def test_render_appends_link_and_trims_only_the_body():
    long = _note("x", "word " * 100)
    tweet = render_note_tweet(long)
    assert len(tweet) <= 280
    assert tweet.endswith(ENGINEERING_URL)  # link never truncated


# --- least-recently-used selection ----------------------------------------------


def test_selects_a_never_posted_note_first_in_pool_order():
    notes = [_note("a", "Alpha note about X"), _note("b", "Beta note about Y")]
    # 'a' already posted; 'b' never has → 'b' is chosen.
    posts = [_post("2026-07-20T12:00:00Z", "Alpha note about X\n" + ENGINEERING_URL)]
    assert select_note(notes, posts)["id"] == "b"


def test_among_posted_notes_picks_the_oldest():
    notes = [_note("a", "Alpha note about X"), _note("b", "Beta note about Y")]
    posts = [
        _post("2026-07-24T12:00:00Z", "Beta note about Y\n" + ENGINEERING_URL),   # recent
        _post("2026-07-10T12:00:00Z", "Alpha note about X\n" + ENGINEERING_URL),  # older
    ]
    assert select_note(notes, posts)["id"] == "a"


def test_never_posted_beats_all_posted_ones():
    notes = [_note("a", "Alpha note about X"), _note("b", "Beta note about Y"), _note("c", "Gamma note Z")]
    posts = [
        _post("2026-07-10T12:00:00Z", "Alpha note about X\n" + ENGINEERING_URL),
        _post("2026-07-11T12:00:00Z", "Beta note about Y\n" + ENGINEERING_URL),
    ]
    assert select_note(notes, posts)["id"] == "c"


def test_ignores_posts_that_never_reached_the_feed():
    notes = [_note("a", "Alpha note about X"), _note("b", "Beta note about Y")]
    # 'a' only appears in a failed post → treated as never posted, chosen over 'b'.
    posts = [
        _post("2026-07-24T12:00:00Z", "Alpha note about X\n" + ENGINEERING_URL, status="error"),
        _post("2026-07-10T12:00:00Z", "Beta note about Y\n" + ENGINEERING_URL),
    ]
    assert select_note(notes, posts)["id"] == "a"


def test_full_rotation_before_any_repeat():
    notes = [_note(c, f"{c} note") for c in "abcd"]
    posts, picked = [], []
    for i in range(4):
        note = select_note(notes, posts)
        picked.append(note["id"])
        posts.append(_post(f"2026-07-2{i}T12:00:00Z", render_note_tweet(note)))
    assert sorted(picked) == ["a", "b", "c", "d"]  # each exactly once


def test_select_none_when_pool_empty():
    assert select_note([], []) is None
