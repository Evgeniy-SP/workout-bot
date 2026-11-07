from app.render import render_strength_summary
from app.db.models import Exercise, SessionSet


def test_tonnage_calculation():
    """Проверяем, что тоннаж считается правильно: reps * weight."""
    ex = Exercise(id=1, name="Присед", kind="strength", sets=3, reps=10)

    # 3 подхода: 10×50, 10×60, 8×60 = 500 + 600 + 480 = 1580 кг
    sets = [
        SessionSet(id=1, exercise_id=1, set_number=1, reps=10, weight_kg="50",
                   completed=True),
        SessionSet(id=2, exercise_id=1, set_number=2, reps=10, weight_kg="60",
                   completed=True),
        SessionSet(id=3, exercise_id=1, set_number=3, reps=8, weight_kg="60",
                   completed=True),
    ]

    text = render_strength_summary(ex, sets)

    assert "Всего повторов: <b>28</b>" in text
    assert "Тоннаж: <b>1580 кг</b>" in text


def test_tonnage_with_text_weight():
    """Проверяем, что текстовый вес ("Своё тело") не ломает подсчет тоннажа."""
    ex = Exercise(id=1, name="Отжимания", kind="strength", sets=3, reps=15)

    # 2 подхода с числом, 1 с текстом — тоннаж должен считаться только для чисел
    sets = [
        SessionSet(id=1, exercise_id=1, set_number=1, reps=15, weight_kg="10",
                   completed=True),
        SessionSet(id=2, exercise_id=1, set_number=2, reps=15, weight_kg="10",
                   completed=True),
        SessionSet(id=3, exercise_id=1, set_number=3, reps=15,
                   weight_kg="Своё тело", completed=True),
    ]

    text = render_strength_summary(ex, sets)

    # 15*10 + 15*10 = 300, третье упражнение не считается
    assert "Тоннаж: <b>300 кг</b>" in text
    assert "Всего повторов: <b>45</b>" in text
