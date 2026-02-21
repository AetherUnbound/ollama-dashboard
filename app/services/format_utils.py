from datetime import datetime, timezone
from dateutil import parser as dateutil_parser
from dateutil.relativedelta import relativedelta
import time


def format_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def format_relative_time(target_dt):
    now = datetime.now(timezone.utc)
    diff = target_dt - now

    days = diff.days
    hours = diff.seconds // 3600
    minutes = (diff.seconds % 3600) // 60

    if days > 0:
        if hours > 12:
            days += 1
        return f"about {days} {'day' if days == 1 else 'days'}"
    elif hours > 0:
        if minutes > 30:
            hours += 1
        return f"about {hours} {'hour' if hours == 1 else 'hours'}"
    elif minutes > 0:
        if minutes < 5:
            return "a few minutes"
        elif minutes < 15:
            return "about 10 minutes"
        elif minutes < 25:
            return "about 20 minutes"
        elif minutes < 45:
            return "about 30 minutes"
        else:
            return "about an hour"
    else:
        return "less than a minute"


def format_duration(started_at, ended_at=None):
    """Return a human-readable duration string between two ISO timestamps."""
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(ended_at) if ended_at else datetime.now()
        rd = relativedelta(end, start)
        parts = []
        if rd.days > 0:
            parts.append(f"{rd.days} {'day' if rd.days == 1 else 'days'}")
        if rd.hours > 0:
            parts.append(f"{rd.hours} {'hour' if rd.hours == 1 else 'hours'}")
        if rd.minutes > 0:
            parts.append(f"{rd.minutes} {'minute' if rd.minutes == 1 else 'minutes'}")
        return ', '.join(parts) if parts else 'less than a minute'
    except Exception:
        return 'unknown'


def format_datetime(value):
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace('Z', '+00:00').split('.')[0])
        else:
            dt = value
        local_dt = dt.astimezone()
        tz_abbr = time.strftime('%Z')
        return local_dt.strftime(f'%-I:%M %p, %b %-d ({tz_abbr})')
    except Exception as e:
        return str(value)


def format_time_ago(value):
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace('Z', '+00:00').split('.')[0])
        else:
            dt = value

        now = datetime.now(dt.tzinfo)
        diff = now - dt

        minutes = diff.total_seconds() / 60
        hours = minutes / 60

        if hours >= 1:
            return f"{int(hours)} {'hour' if int(hours) == 1 else 'hours'}"
        elif minutes >= 1:
            return f"{int(minutes)} {'minute' if int(minutes) == 1 else 'minutes'}"
        else:
            return "less than a minute"
    except Exception as e:
        return str(value)
