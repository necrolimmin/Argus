from datetime import datetime


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def is_scheduled(windows: list[dict], now: datetime) -> bool:
    """True when recognition should run at local time `now`.

    No windows means around the clock. A window whose end is before its
    start runs overnight, e.g. 20:00–06:00, and the night belongs to the
    day it started on.
    """
    if not windows:
        return True
    minute = now.hour * 60 + now.minute
    today = now.isoweekday()
    yesterday = 7 if today == 1 else today - 1
    for w in windows:
        start, end = _minutes(w["start"]), _minutes(w["end"])
        days = set(w["days"])
        if start == end:
            if today in days:
                return True
        elif start < end:
            if today in days and start <= minute < end:
                return True
        else:
            if today in days and minute >= start:
                return True
            if yesterday in days and minute < end:
                return True
    return False
