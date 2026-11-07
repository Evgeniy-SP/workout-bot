from datetime import datetime, timezone
from app.utils import to_msk, fmt_msk_date, fmt_msk_datetime


def test_to_msk_from_utc():
    """Проверяем, что UTC переводится в МСК (+3 часа)."""
    utc_time = datetime(2026, 11, 8, 21, 0, tzinfo=timezone.utc)
    msk_time = to_msk(utc_time)

    assert msk_time.hour == 0
    assert msk_time.day == 9  # 21:00 UTC + 3 = 00:00 следующего дня
    assert msk_time.tzinfo.utcoffset(None).total_seconds() == 3 * 3600


def test_to_msk_from_naive():
    """Naive datetime считаем UTC и тоже переводим в МСК."""
    naive_time = datetime(2026, 11, 8, 21, 0)  # без tzinfo
    msk_time = to_msk(naive_time)

    assert msk_time.hour == 0
    assert msk_time.day == 9


def test_fmt_msk():
    """Проверяем форматирование даты и даты-времени."""
    utc_time = datetime(2026, 11, 8, 21, 30, tzinfo=timezone.utc)

    assert fmt_msk_date(utc_time) == "09.11.2026"
    # 21:30 UTC + 3 = 00:30 следующего дня
    assert fmt_msk_datetime(utc_time) == "09.11.2026 00:30"
