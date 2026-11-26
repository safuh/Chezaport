"""Normalize provider match reports into stable, typed event records.

Provider feeds do not always expose event IDs. We therefore derive a content
fingerprint and retain an occurrence number for exact duplicates. The key is
stable across harmless provider reordering, while duplicate same-minute events
remain distinct. A changed event payload intentionally receives a new key.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from typing import Any

_EVENT_COLLECTIONS = {
    "goal": "goals",
    "booking": "bookings",
    "substitution": "substitutions",
}


def _canonical_json(value: Mapping[str, Any]) -> str:
    """Serialize an event deterministically for fingerprinting."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def normalize_match_events(
    report: Mapping[str, Any],
    *,
    provider: str,
    fixture_id: str,
) -> list[dict[str, Any]]:
    """Return provider-neutral event rows without discarding duplicate events.

    Each row includes its original provider payload for auditability. The
    occurrence suffix distinguishes identical events in the same report;
    event ordering in the source is not used as identity.
    """
    if not provider.strip():
        raise ValueError("provider must not be blank")
    if not fixture_id.strip():
        raise ValueError("fixture_id must not be blank")

    rows: list[dict[str, Any]] = []
    for event_type, collection_name in _EVENT_COLLECTIONS.items():
        raw_events = report.get(collection_name, ())
        if raw_events is None:
            continue
        if not isinstance(raw_events, (list, tuple)):
            raise ValueError(f"{collection_name} must be a list")

        occurrences: Counter[str] = Counter()
        for raw_event in raw_events:
            if not isinstance(raw_event, Mapping):
                raise ValueError(f"{collection_name} entries must be objects")
            payload = dict(raw_event)
            serialized = _canonical_json(payload)
            digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
            occurrence = occurrences[digest]
            occurrences[digest] += 1
            rows.append(
                {
                    "provider": provider,
                    "fixture_id": fixture_id,
                    "event_type": event_type,
                    "source_key": f"{event_type}:{digest}:{occurrence}",
                    "minute": payload.get("minute"),
                    "payload": payload,
                }
            )

    return sorted(
        rows,
        key=lambda row: (
            row["minute"] is None,
            row["minute"] if row["minute"] is not None else 0,
            row["event_type"],
            row["source_key"],
        ),
    )
