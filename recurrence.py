"""Validates the extractor's recurrence data and turns it into a Google
Calendar RRULE plus a bilingual one-line description for the preview."""

from datetime import datetime, timedelta

FREQS = ("DAILY", "WEEKLY", "MONTHLY", "YEARLY")
WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")  # index == date.weekday()

_EN_DAY = {
    "MO": "Monday", "TU": "Tuesday", "WE": "Wednesday", "TH": "Thursday",
    "FR": "Friday", "SA": "Saturday", "SU": "Sunday",
}
_RU_DAY = {  # dative plural, for "по вторникам"
    "MO": "понедельникам", "TU": "вторникам", "WE": "средам", "TH": "четвергам",
    "FR": "пятницам", "SA": "субботам", "SU": "воскресеньям",
}
_EN_UNIT = {"DAILY": "day", "WEEKLY": "week", "MONTHLY": "month", "YEARLY": "year"}
_RU_EVERY = {
    "DAILY": "Каждый день", "WEEKLY": "Каждую неделю",
    "MONTHLY": "Каждый месяц", "YEARLY": "Каждый год",
}
_RU_UNIT_FORMS = {  # (1, 2-4, 5+) for "Каждые N ..."
    "DAILY": ("день", "дня", "дней"),
    "WEEKLY": ("неделю", "недели", "недель"),
    "MONTHLY": ("месяц", "месяца", "месяцев"),
    "YEARLY": ("год", "года", "лет"),
}


def _ru_plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _parse_date(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def normalize_event(event):
    """Cleans event["recurrence"] in place: drops it if unusable, otherwise
    fills defaults and moves event["date"] forward to the first date that
    actually matches the weekday rule (a weekly Tuesday meeting must start on
    a Tuesday, whatever date the model guessed)."""
    raw = event.get("recurrence")
    start = _parse_date(event.get("date"))
    if not isinstance(raw, dict) or start is None:
        event.pop("recurrence", None)
        return

    freq = str(raw.get("freq") or "").upper()
    if freq not in FREQS:
        event.pop("recurrence", None)
        return

    until = _parse_date(raw.get("until"))
    if until and until < start:
        event.pop("recurrence", None)
        return
    count = None if until else _positive_int(raw.get("count"))

    by_day = []
    if freq == "WEEKLY":
        given = {str(d).upper() for d in raw.get("by_day") or []}
        by_day = [d for d in WEEKDAYS if d in given] or [WEEKDAYS[start.weekday()]]
        wanted = {WEEKDAYS.index(d) for d in by_day}
        first = next(start + timedelta(days=i) for i in range(7) if (start + timedelta(days=i)).weekday() in wanted)
        if until and until < first:
            event.pop("recurrence", None)
            return
        event["date"] = first.isoformat()

    event["recurrence"] = {
        "freq": freq,
        "interval": _positive_int(raw.get("interval")) or 1,
        "by_day": by_day,
        "until": until.isoformat() if until else None,
        "count": count,
    }


def rrule(rec):
    parts = [f"FREQ={rec['freq']}"]
    if rec["interval"] > 1:
        parts.append(f"INTERVAL={rec['interval']}")
    if rec["by_day"]:
        parts.append("BYDAY=" + ",".join(rec["by_day"]))
    if rec["count"]:
        parts.append(f"COUNT={rec['count']}")
    if rec["until"]:
        # Timed events need a UTC UNTIL; end-of-day UTC keeps the last day's
        # occurrence included for any local timezone in use here.
        parts.append("UNTIL=" + rec["until"].replace("-", "") + "T235959Z")
    return "RRULE:" + ";".join(parts)


def describe(rec):
    """Returns (english, russian) text, e.g. "Every week on Tuesday"."""
    freq, n = rec["freq"], rec["interval"]

    if n == 1:
        en = f"Every {_EN_UNIT[freq]}"
        ru = _RU_EVERY[freq]
    else:
        en = f"Every {n} {_EN_UNIT[freq]}s"
        ru = f"Каждые {n} {_ru_plural(n, *_RU_UNIT_FORMS[freq])}"

    if rec["by_day"]:
        en += " on " + ", ".join(_EN_DAY[d] for d in rec["by_day"])
        ru += " по " + ", ".join(_RU_DAY[d] for d in rec["by_day"])
    if rec["until"]:
        en += f", until {rec['until']}"
        ru += f", до {rec['until']}"
    elif rec["count"]:
        en += f", {rec['count']} times"
        ru += f", {rec['count']} {_ru_plural(rec['count'], 'раз', 'раза', 'раз')}"
    return en, ru
