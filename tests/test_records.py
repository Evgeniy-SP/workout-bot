import pytest
from app.db.models import SessionSet
from app.services.training_service import calculate_personal_records


def test_calculate_personal_records():
    """Проверяем расчет рекордов."""
    # 3 подхода: 10x50 (500), 5x80 (400), 12x60 (720) - рекорд веса 80, рекорд объема 720
    sets = [
        SessionSet(reps=10, weight_kg="50"),
        SessionSet(reps=5, weight_kg="80"),
        SessionSet(reps=12, weight_kg="60"),
    ]

    prs = calculate_personal_records(sets)

    assert prs["max_weight"] == 80.0
    assert prs["max_volume"] == 720.0
    assert prs["best_set"].reps == 12  # Лучший подход по тоннажу - 12x60


def test_calculate_personal_records_with_text_weight():
    """Текстовые веса не должны ломать подсчет."""
    sets = [
        SessionSet(reps=10, weight_kg="Своё тело"),
        SessionSet(reps=10, weight_kg="20"),
    ]

    prs = calculate_personal_records(sets)

    assert prs["max_weight"] == 20.0
    assert prs["max_volume"] == 200.0


def test_calculate_personal_records_empty():
    """Пустой список возвращает нули."""
    assert calculate_personal_records([])["max_weight"] == 0.0
