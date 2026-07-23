"""Pure helpers for mapping capture events into an edited media timebase.

This module intentionally depends only on the Python standard library.  Capture
and rendering tools can therefore share the timestamp contract without loading
Playwright or any project-specific browser code.
"""

from __future__ import annotations

import json
import os


DEFAULT_SOURCE_WIDTH = 1920
DEFAULT_SOURCE_HEIGHT = 1080


def transform_events(events, trim_lead=0.4, speed=1.0):
    """Return capture events expressed in edited-media seconds.

    Events before the retained media range are omitted.  The original timestamp
    is preserved as ``rawT`` so downstream camera and cursor QA can audit the
    conversion.
    """
    trim_lead = float(trim_lead)
    speed = float(speed)
    if speed <= 0:
        raise ValueError("speed must be greater than zero")

    transformed = []
    for event in events:
        if "t" not in event:
            continue
        edited = (float(event["t"]) - trim_lead) / speed
        if edited < 0:
            continue
        item = dict(event)
        item["rawT"] = event["t"]
        item["t"] = round(edited, 4)
        transformed.append(item)
    return transformed


def normalize_events_file(
    raw_events,
    edited_events,
    trim_lead=0.4,
    speed=1.0,
    *,
    source_width=DEFAULT_SOURCE_WIDTH,
    source_height=DEFAULT_SOURCE_HEIGHT,
):
    """Write a versioned event timeline alongside a normalized media file.

    ``None`` is returned when the raw event file is absent, matching the legacy
    ``shoot.py`` behavior for recordings that do not emit interaction events.
    """
    if not raw_events or not os.path.exists(raw_events):
        return None

    with open(raw_events, encoding="utf-8") as handle:
        raw_payload = json.load(handle)
    events = raw_payload.get("events", []) if isinstance(raw_payload, dict) else raw_payload
    if not isinstance(events, list):
        raise ValueError("raw event payload must be a list or an object containing events[]")

    trim_lead = float(trim_lead)
    speed = float(speed)
    payload = {
        "schemaVersion": 2,
        "timebase": "edited-media-seconds",
        "transform": {
            "trimLeadSec": trim_lead,
            "speed": speed,
            "formula": "edited=(raw-trimLead)/speed",
        },
        "sourceViewport": {"width": int(source_width), "height": int(source_height)},
        "events": transform_events(events, trim_lead, speed),
    }
    parent = os.path.dirname(os.path.abspath(edited_events))
    os.makedirs(parent, exist_ok=True)
    with open(edited_events, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    return edited_events


__all__ = ["normalize_events_file", "transform_events"]
