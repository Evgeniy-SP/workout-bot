import pytest
from app.db.models import SessionSet
from app.services.training_service import calculate_personal_records


def test_calculate_personal_records():
    """Проверяем расчет рекордов."""
    sets = [
        SessionSet(reps=10, weight_kg="50"),
        SessionSet(reps=5, weight_kg="80"),
        SessionSet(reps=12, weight_kg="60"),
    ]

    prs = calculate_personal_records(sets)

    assert prs["max_weight_val"] == 80.0
    assert prs["max_weight_str"] == "80"
    assert prs["max_volume"] == 720.0
    assert prs["best_set"].reps == 12


def test_calculate_personal_records_with_text_weight():
    """Текстовые веса не должны ломать подсчет."""
    sets = [
        SessionSet(reps=10, weight_kg="Своё тело"),
        SessionSet(reps=10, weight_kg="20"),
    ]

    prs = calculate_personal_records(sets)

    assert prs["max_weight_val"] == 20.0
    assert prs["max_weight_str"] == "20"
    assert prs["max_volume"] == 200.0


def test_calculate_personal_records_empty():
    """Пустой список возвращает нули."""
    prs = calculate_personal_records([])
    assert prs["max_weight_val"] == 0.0
    assert prs["max_volume"] == 0.0