from datetime import datetime, timezone, timedelta

_VN_TZ = timezone(timedelta(hours=7))


def now_vn() -> datetime:
    """Current datetime in Vietnam timezone (UTC+7), stored as naive datetime."""
    return datetime.now(_VN_TZ).replace(tzinfo=None)
