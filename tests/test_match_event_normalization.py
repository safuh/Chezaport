"""Tests for provider match-event normalization and duplicate preservation."""

import pytest

from chezaport.sports.services.match_events import normalize_match_events


def test_normalizer_preserves_same_minute_and_identical_duplicate_events() -> None:
    report = {
        "goals": [
            {"minute": 32, "scorer_external_id": "p1"},
            {"minute": 32, "scorer_external_id": "p1"},
            {"minute": 32, "scorer_external_id": "p2"},
        ],
        "bookings": [{"minute": 32, "player_external_id": "p3", "card": "yellow"}],
    }

    events = normalize_match_events(
        report, provider="football-data-org", fixture_id="fixture-1"
    )

    goals = [event for event in events if event["event_type"] == "goal"]
    assert len(goals) == 3
    assert len({event["source_key"] for event in goals}) == 3
    assert all(event["minute"] == 32 for event in goals)
    assert {event["payload"]["scorer_external_id"] for event in goals} == {"p1", "p2"}


def test_normalizer_keys_are_independent_of_source_order() -> None:
    first = {
        "goals": [
            {"minute": 10, "scorer_external_id": "p1"},
            {"minute": 80, "scorer_external_id": "p2"},
        ]
    }
    second = {"goals": list(reversed(first["goals"]))}

    keys_a = {
        event["source_key"]
        for event in normalize_match_events(first, provider="provider", fixture_id="f1")
    }
    keys_b = {
        event["source_key"]
        for event in normalize_match_events(second, provider="provider", fixture_id="f1")
    }
    assert keys_a == keys_b


def test_normalizer_rejects_malformed_collections() -> None:
    with pytest.raises(ValueError, match="goals must be a list"):
        normalize_match_events(
            {"goals": {"minute": 10}}, provider="provider", fixture_id="f1"
        )


def test_normalizer_rejects_blank_scope() -> None:
    with pytest.raises(ValueError, match="provider"):
        normalize_match_events({}, provider=" ", fixture_id="f1")
