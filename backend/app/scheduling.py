from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .db import utc


def next_run(schedule: dict, tz: str, after: datetime, anchor: datetime | None = None):
    after = utc(after)
    zone = ZoneInfo(tz)
    local = after.astimezone(zone)
    kind = schedule["kind"]
    n = schedule.get("interval", 1)
    if kind == "hours":
        base = utc(anchor) if anchor else after
        steps = max(1, int((after - base).total_seconds() // (n * 3600)) + 1)
        return base + timedelta(hours=n * steps)
    hour, minute = map(int, schedule.get("time", "09:00").split(":"))
    base_date = utc(anchor).astimezone(zone).date() if anchor else local.date()
    for delta in range(0, 740):
        day = local.date() + timedelta(days=delta)
        if kind == "weekly" and day.weekday() != schedule.get("weekday", 0):
            continue
        if kind == "days" and (day - base_date).days % n:
            continue
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
        # Round-trip resolves nonexistent DST wall times forward, and uses fold=0 once.
        candidate = candidate.astimezone(timezone.utc)
        if candidate > after:
            return candidate
    raise ValueError("다음 실행 시각 계산 실패")
