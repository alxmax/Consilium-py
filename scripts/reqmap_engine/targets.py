# implements: ARCH-MAP-007
"""Optional planning sidecar — lanes, bars, milestone due dates, release cadence.

Reads `requirements/_planning.json` first, then legacy `_targets.json`."""
import datetime
import json
import os
import re

PLANNING_FILES = ("_planning.json", "_targets.json")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_milestone_entry(raw):
    if raw is None:
        return None
    if isinstance(raw, str):
        return {"due": raw} if _DATE_RE.match(raw.strip()) else None
    if not isinstance(raw, dict):
        return None
    out = {}
    due = raw.get("due")
    if isinstance(due, str) and _DATE_RE.match(due.strip()):
        out["due"] = due.strip()
    label = raw.get("label") or raw.get("note")
    if isinstance(label, str) and label.strip():
        out["label"] = label.strip()
    return out or None


def _parse_bar(raw):
    if not isinstance(raw, dict):
        return None
    title = raw.get("title") or raw.get("name")
    start = raw.get("start")
    end = raw.get("end") or raw.get("due")
    if not isinstance(title, str) or not title.strip():
        return None
    if not isinstance(start, str) or not _DATE_RE.match(start.strip()):
        return None
    if not isinstance(end, str) or not _DATE_RE.match(end.strip()):
        end = start
    out = {"title": title.strip(), "start": start.strip(), "end": end.strip()}
    lane = raw.get("lane")
    if isinstance(lane, str) and lane.strip():
        out["lane"] = lane.strip()
    ms = raw.get("milestone")
    if isinstance(ms, str) and ms.strip():
        out["milestone"] = ms.strip()
    rid = raw.get("req") or raw.get("reqId") or raw.get("id")
    if isinstance(rid, str) and rid.strip() and rid.strip() != out["title"]:
        out["req"] = rid.strip()
    prog = raw.get("progress")
    if isinstance(prog, (int, float)) and 0 <= prog <= 100:
        out["progress"] = int(round(prog))
    return out


# ---------- release cadence ----------
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
PERIODS = {"week": "week", "weekly": "week", "month": "month", "monthly": "month"}
# One default per period, because "on" means a different thing in each: a weekday for a
# week, a day-of-month (or "last") for a month. A single default would be wrong for one
# of them, and silently so.
PERIOD_DEFAULT_ON = {"week": "friday", "month": "last"}
CADENCE_DEFAULTS = {"every": "week", "on": "friday", "lane": "Release"}
# A plan can span years; one marker per week over a decade is 520 vertical lines and an
# unreadable chart. The cap is a rendering limit, not a planning opinion — it truncates
# the tail and the count says so, rather than silently thinning the series.
CADENCE_MAX = 120


def _cadence_month_on(on):
    """The day of the month a `cadence` block asks for, or None to keep the default.

    "last" is the default because a month's end is what a reader means by "end of
    month", and it is the only choice that lands in every month: a plan pinned to the
    30th silently skips February. Three accepted spellings were an `elif` chain inside
    `_parse_cadence`, which is one nesting level per branch; as early returns they are
    a list of what the key accepts."""
    if isinstance(on, str) and on.strip().lower() == "last":
        return "last"
    if isinstance(on, int) and 1 <= on <= 28:
        return on
    if isinstance(on, str) and on.strip().isdigit() and 1 <= int(on) <= 28:
        return int(on.strip())
    return None


def _parse_cadence(raw):
    """Normalise the optional `cadence` block, or None when absent/unusable.

    `week` and `month` exist; anything else yields None rather than a series computed on
    a guess. A plan that asked for a fortnight and silently got a week would be wrong on
    every other marker, which is worse than no marker at all."""
    if raw is True:
        raw = {}
    if not isinstance(raw, dict):
        return None
    every = raw.get("every")
    if every is None:
        period = CADENCE_DEFAULTS["every"]
    elif isinstance(every, str) and every.strip().lower() in PERIODS:
        period = PERIODS[every.strip().lower()]
    else:
        return None
    out = dict(CADENCE_DEFAULTS)
    out["every"] = period
    out["on"] = PERIOD_DEFAULT_ON[period]
    on = raw.get("on")
    if isinstance(on, str) and period == "week" and on.strip().lower() in WEEKDAYS:
        out["on"] = on.strip().lower()
    elif period == "month":
        day = _cadence_month_on(on)
        if day is not None:
            out["on"] = day
    lane = raw.get("lane")
    if isinstance(lane, str) and lane.strip():
        out["lane"] = lane.strip()
    for key in ("from", "until"):
        val = raw.get(key)
        if isinstance(val, str) and _DATE_RE.match(val.strip()):
            out[key] = val.strip()
    return out


def _plan_span(out):
    """(first, last) ISO dates the plan already covers, from its bars and milestone
    dues. When it covers nothing the span runs from today to `default_horizon()`.

    That reverses an earlier "a cadence needs something to run alongside, and inventing
    a span from today would put markers on an empty chart". The case it was written for
    is the case that turned out to matter: a repo that has planned nothing yet is
    exactly the one that needs a calendar to plan ON. An empty chart with months on it
    is a canvas; an empty chart with no months is a dead end, and `init` now seeds a
    `_planning.json` precisely so a new repo starts with one (REQ-PLANHORIZON-1010)."""
    dates = []
    for bar in out.get("bars", []):
        dates.append(bar["start"])
        dates.append(bar["end"])
    for entry in out.get("milestones", {}).values():
        if entry.get("due"):
            dates.append(entry["due"])
    if not dates:
        return datetime.date.today().isoformat(), default_horizon()
    return min(dates), max(dates)


def _month_end(year, month):
    """The last day of that month, without a calendar import: day 1 of the next month,
    minus one."""
    nxt = datetime.date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return nxt - datetime.timedelta(days=1)


def default_horizon(today=None):
    # implements: ARCH-ROADMAP-038  # implements: REQ-PLANHORIZON-1010
    """How far a cadence runs when its author named no `until`: the end of this year,
    or three months out, whichever is later.

    The year end alone is a plan that shrinks as the year does — in December it would
    show one month, which is the point at which a reader needs the next quarter most.
    Three months alone never shows the year. Taking the later of the two means the chart
    reaches the end of the year for most of it and rolls into the next one near the
    close: asked in December 2026 it answers February 2027."""
    d = today or datetime.date.today()
    year_end = datetime.date(d.year, 12, 31)
    month = d.month + 3
    year = d.year + (month - 1) // 12
    quarter_out = _month_end(year, (month - 1) % 12 + 1)
    return max(year_end, quarter_out).isoformat()


def _release_dates(cadence, first, last):
    """The cadence's dates from `first` through `last`, inclusive, as ISO strings.

    Computed HERE and emitted, not recomputed in the viewer: a second definition in
    JavaScript is how the CLI and the chart come to disagree about when a release lands."""
    start = cadence.get("from") or first
    # `last` is the final dated thing in the plan, which in a fresh repo is nothing at
    # all. Falling back to the shared horizon means a cadence draws a calendar before
    # anything is scheduled on it — which is what a new repo has.
    end = cadence.get("until") or last or default_horizon()
    if not start or not end or start > end:
        return []
    try:
        day = datetime.date(*(int(p) for p in start.split("-")))
        stop = datetime.date(*(int(p) for p in end.split("-")))
    except (TypeError, ValueError):
        return []
    dates = []
    if cadence["every"] == "month":
        year, month = day.year, day.month
        while len(dates) < CADENCE_MAX:
            on = cadence["on"]
            when = _month_end(year, month) if on == "last" else datetime.date(year, month, on)
            if when > stop:
                break
            if when >= day:
                dates.append(when.isoformat())
            year, month = year + (month == 12), 1 if month == 12 else month + 1
        return dates
    target = WEEKDAYS.index(cadence["on"])
    day += datetime.timedelta(days=(target - day.weekday()) % 7)
    while day <= stop and len(dates) < CADENCE_MAX:
        dates.append(day.isoformat())
        day += datetime.timedelta(days=7)
    return dates


def _read_planning_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def load_targets(reqs_dir):
    """Parsed planning sidecar, or {} when absent or invalid (fail-open)."""
    raw = None
    for name in PLANNING_FILES:
        path = os.path.join(reqs_dir or ".", name)
        if os.path.isfile(path):
            raw = _read_planning_file(path)
            if raw is not None:
                break
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        return {}

    out = {}
    milestones = raw.get("milestones")
    if isinstance(milestones, dict):
        clean_ms = {}
        for ms, entry in milestones.items():
            if not isinstance(ms, str) or not ms.strip():
                continue
            parsed = _parse_milestone_entry(entry)
            if parsed:
                clean_ms[ms.strip()] = parsed
        if clean_ms:
            out["milestones"] = clean_ms

    lanes = raw.get("lanes")
    if isinstance(lanes, list):
        clean_lanes = [s.strip() for s in lanes if isinstance(s, str) and s.strip()]
        if clean_lanes:
            out["lanes"] = clean_lanes

    bars = raw.get("bars")
    if isinstance(bars, list):
        clean_bars = []
        for entry in bars:
            parsed = _parse_bar(entry)
            if parsed:
                clean_bars.append(parsed)
        if clean_bars:
            out["bars"] = clean_bars

    # Last, because it needs the span the bars and milestones above define.
    # implements: REQ-PLANCADENCE-1000
    cadence = _parse_cadence(raw.get("cadence"))
    if cadence:
        first, last = _plan_span(out)
        dates = _release_dates(cadence, first, last)
        if dates:
            out["cadence"] = cadence
            out["releases"] = dates
    return out

