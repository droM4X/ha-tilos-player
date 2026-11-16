"""Tests for the pure progress model (no Home Assistant import)."""

from datetime import datetime, timedelta, timezone

from progress import (
    PLAYBACK_PROGRESS_VERSION,
    ProgressBook,
    effective_position,
    format_now_playing,
    is_finished,
    is_resumable,
)

KEY = "tilos-20260717-100000-120000"
KEY2 = "tilos-20260718-100000-120000"
TS = 1784282400000  # 2026-07-17T10:00:00Z
NOW = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)


def test_format_now_playing_joins_show_title_and_date():
    assert format_now_playing("Szabadlábon", "Tracklistával", TS) == (
        "Szabadlábon – Tracklistával (2026.07.17.)"
    )


def test_format_now_playing_drops_a_leading_date_from_the_title():
    assert format_now_playing("Szabadlábon", "2026.07.17. - Tracklistával", TS) == (
        "Szabadlábon – Tracklistával (2026.07.17.)"
    )


def test_format_now_playing_keeps_a_title_that_is_only_a_date():
    assert format_now_playing("Szabadlábon", "2026.07.17.", TS) == (
        "Szabadlábon – 2026.07.17. (2026.07.17.)"
    )


def test_format_now_playing_without_show_name():
    assert format_now_playing("", "Tracklistával", TS) == (
        "Tracklistával (2026.07.17.)"
    )


def test_format_now_playing_without_timestamp():
    assert format_now_playing("Szabadlábon", "Tracklistával", 0) == (
        "Szabadlábon – Tracklistával"
    )


def test_effective_position_extrapolates_while_playing():
    attrs = {
        "media_position": 100.0,
        "media_position_updated_at": NOW - timedelta(seconds=10),
    }
    assert effective_position(attrs, "playing", NOW) == 110.0


def test_effective_position_does_not_extrapolate_when_paused():
    attrs = {
        "media_position": 100.0,
        "media_position_updated_at": NOW - timedelta(seconds=10),
    }
    assert effective_position(attrs, "paused", NOW) == 100.0


def test_effective_position_without_update_timestamp_returns_media_position():
    assert effective_position({"media_position": 42}, "playing", NOW) == 42.0


def test_effective_position_returns_none_without_media_position():
    assert effective_position({}, "playing", NOW) is None


def test_effective_position_returns_none_for_null_position():
    assert effective_position({"media_position": None}, "playing", NOW) is None


def test_is_finished_within_the_finish_margin():
    assert is_finished(4775, 4800) is True


def test_is_finished_ignores_unknown_duration():
    assert is_finished(4775, 0) is False


def test_is_resumable_needs_the_minimum_position():
    assert is_resumable(29, 4800) is False
    assert is_resumable(30, 4800) is True


def test_is_resumable_requires_room_before_the_end():
    assert is_resumable(4780, 4800) is False


def test_is_resumable_with_unknown_duration():
    assert is_resumable(120, 0) is True


def test_record_keeps_a_resumable_position():
    book = ProgressBook()
    assert book.record(KEY, 120, 4800, "Szabadlábon", NOW) is True
    assert book.has(KEY) is True
    assert book.position(KEY) == 120


def test_record_stores_the_position_as_whole_seconds():
    book = ProgressBook()
    book.record(KEY, 120.6, 4800, "Szabadlábon", NOW)
    assert book.position(KEY) == 121


def test_record_of_a_position_below_the_minimum_clears_the_entry():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    assert book.record(KEY, 5, 4800, "Szabadlábon", NOW) is True
    assert book.has(KEY) is False


def test_record_near_the_end_marks_the_episode_finished():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    assert book.record(KEY, 4780, 4800, "Szabadlábon", NOW) is True
    assert book.has(KEY) is False


def test_record_without_duration_keeps_the_entry_resumable():
    book = ProgressBook()
    assert book.record(KEY, 120, 0, "Szabadlábon", NOW) is True
    assert book.has(KEY) is True


def test_record_returns_false_when_only_the_position_moved():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    assert (
        book.record(KEY, 150, 4800, "Szabadlábon", NOW + timedelta(seconds=30)) is False
    )


def test_clear_reports_the_change_once():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    assert book.clear(KEY) is True
    assert book.clear(KEY) is False


def test_show_names_returns_the_shows_with_a_stored_position():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    book.record(KEY2, 60, 4800, "Másik műsor", NOW)
    assert book.show_names() == {"Szabadlábon", "Másik műsor"}


def test_has_any_checks_keys():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    assert book.has_any([KEY2, KEY]) is True
    assert book.has_any([KEY2]) is False


def test_oldest_entry_is_evicted_past_the_limit():
    book = ProgressBook(max_entries=2)
    book.record(KEY, 100, 4800, "A", NOW)
    book.record(KEY2, 100, 4800, "B", NOW + timedelta(seconds=1))
    book.record(
        "tilos-20260719-100000-120000", 100, 4800, "C", NOW + timedelta(seconds=2)
    )
    assert book.has(KEY) is False
    assert book.has(KEY2) is True


def test_take_dirty_reports_and_resets():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    assert book.take_dirty() is True
    assert book.take_dirty() is False


def test_record_of_a_moved_position_marks_the_book_dirty():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    book.take_dirty()
    book.record(KEY, 150, 4800, "Szabadlábon", NOW + timedelta(seconds=30))
    assert book.take_dirty() is True


def test_clear_marks_the_book_dirty_once():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    book.take_dirty()
    assert book.clear(KEY) is True
    assert book.take_dirty() is True
    assert book.clear(KEY) is False
    assert book.take_dirty() is False


def test_payload_round_trip():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    restored = ProgressBook.from_payload(book.to_payload())
    assert restored.position(KEY) == 120
    assert restored.get(KEY).show_name == "Szabadlábon"
    assert restored.get(KEY).updated == NOW.isoformat()
    assert restored.get(KEY).duration == 4800


def test_from_payload_tolerates_garbage():
    for payload in (None, [], "x", {}, {"entries": []}, {"entries": {"k": 5}}):
        assert ProgressBook.from_payload(payload).to_payload() == {
            "version": PLAYBACK_PROGRESS_VERSION,
            "entries": {},
        }


def test_from_payload_tolerates_bad_entries():
    payload = {
        "entries": {
            "k": {"position": "x"},
            KEY: {
                "position": 90,
                "duration": 4800,
                "show_name": "Szabadlábon",
                "updated": NOW.isoformat(),
            },
        }
    }
    book = ProgressBook.from_payload(payload)
    assert book.has("k") is False
    assert book.has(KEY) is True
