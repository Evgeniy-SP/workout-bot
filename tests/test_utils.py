from app.utils import format_duration, parse_minutes_to_seconds

def test_format_duration():
    """Проверяем, что время форматируется красиво."""
    assert format_duration(1800) == "30 мин"
    assert format_duration(90) == "1 мин 30 сек"
    assert format_duration(45) == "45 сек"
    assert format_duration(None) == "по факту"

def test_parse_minutes_to_seconds():
    """Проверяем, что парсер понимает точки, запятые и отсекает мусор."""
    assert parse_minutes_to_seconds("5") == 300
    assert parse_minutes_to_seconds("1.5") == 90
    assert parse_minutes_to_seconds("1,5") == 90
    assert parse_minutes_to_seconds("abc") is None
    assert parse_minutes_to_seconds("-1") is None
