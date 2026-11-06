"""Храним длительность в секундах (int), вводим/показываем в минутах."""


def parse_minutes_to_seconds(text: str) -> int | None:
    """'5' → 300, '1.5' → 90, '1,5' → 90, 'abc'/'-1' → None."""
    text = text.strip().replace(",", ".")
    try:
        minutes = float(text)
    except ValueError:
        return None
    if minutes <= 0:
        return None
    return int(round(minutes * 60))


def format_duration(seconds: int | None) -> str:
    """1800 → '30 мин', 90 → '1 мин 30 сек', 45 → '45 сек', None → 'по факту'."""
    if seconds is None:
        return "по факту"
    if seconds < 60:
        return f"{seconds} сек"
    mins, secs = divmod(seconds, 60)
    if secs == 0:
        return f"{mins} мин"
    return f"{mins} мин {secs} сек"


# ─── Московское время ───
from datetime import datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3))


def to_msk(dt: datetime) -> datetime:
    """Конвертирует datetime в московское время.

    Naive datetime считаем UTC (так БД отдаёт через server_default=now()).
    Aware — просто переводим в нужный пояс.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MSK)


def fmt_msk_date(dt: datetime) -> str:
    """Дата в формате ДД.ММ.ГГГГ по Москве."""
    return to_msk(dt).strftime("%d.%m.%Y")


def fmt_msk_datetime(dt: datetime) -> str:
    """Дата и время в формате ДД.ММ.ГГГГ ЧЧ:ММ по Москве."""
    return to_msk(dt).strftime("%d.%m.%Y %H:%M")


def format_weight(weight: str | None) -> str:
    """Красиво выводит вес: добавляет 'кг' если это число, или оставляет текст."""
    if not weight:
        return "без веса"
    try:
        float(weight)  # проверяем, число ли это
        return f"{weight} кг"
    except ValueError:
        return weight  # если текст (например, "Своё тело"), возвращаем как есть
