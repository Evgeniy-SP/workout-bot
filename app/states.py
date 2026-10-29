"""FSM-состояния: «в каком шаге диалога находится пользователь».

Когда пользователь нажимает кнопку редактирования — бот переходит
в соответствующее состояние и ждёт ввода. После сохранения — очищает.
"""
from aiogram.fsm.state import State, StatesGroup


class WorkoutEdit(StatesGroup):
    # Переименование тренировки
    renaming_type = State()

    # Редактирование полей упражнения
    editing_exercise_name = State()
    editing_exercise_sets = State()
    editing_exercise_reps = State()
    editing_exercise_weight = State()
    editing_exercise_duration = State()


class WorkoutCreate(StatesGroup):
    """Создание новой тренировки и упражнений в ней."""
    adding_type_name = State()          # ввод названия новой тренировки
    adding_type_description = State()

    # Создание упражнения
    adding_exercise_kind = State()      # выбор: силовое / кардио
    adding_exercise_name = State()
    adding_exercise_sets = State()      # только для силовых
    adding_exercise_reps = State()      # только для силовых
    adding_exercise_weight = State()    # только для силовых
    adding_exercise_duration = State()  # только для кардио/разминки


class TrainingFSM(StatesGroup):
    """Ввод фактических значений во время тренировки."""
    entering_reps = State()
    entering_weight = State()
    entering_duration = State()
