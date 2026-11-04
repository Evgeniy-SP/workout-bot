"""Фабрики inline-клавиатур."""
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from app.db.models import Exercise, WorkoutType
from app.utils import format_weight, format_duration


def workouts_list_kb(workouts: list[WorkoutType],
                     active_wt_id: int | None = None,
                     new_wt_ids: set[int] = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    new_wt_ids = new_wt_ids or set()

    for w in workouts:
        marker = " ▶️" if w.id == active_wt_id else ""
        new_marker = "🆕 " if w.id in new_wt_ids else ""
        kb.button(text=f"{new_marker}🏋️ {w.name}{marker}",
                  callback_data=f"wt:{w.id}")

    kb.button(text="➕ Новая тренировка", callback_data="wt_new")
    kb.button(text="📦 Архив тренировок", callback_data="wt_arch_list")
    kb.adjust(1)
    return kb.as_markup()


def workout_card_kb(wt: WorkoutType,
                    active_session_id: int | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if active_session_id:
        kb.button(text="▶️ Продолжить тренировку",
                  callback_data=f"tr_list:{active_session_id}")
    else:
        kb.button(text="▶️ Начать тренировку",
                  callback_data=f"tr_start:{wt.id}")

    kb.button(text="👀 Упражнения", callback_data=f"wt_ex:{wt.id}")

    rot_text = "🔄 В ротации: Да" if wt.is_in_rotation else "⏸ Не в ротации"
    kb.button(text=rot_text, callback_data=f"wt_toggle_rot:{wt.id}")

    kb.button(text="✏️ Переименовать", callback_data=f"wt_ren:{wt.id}")
    kb.button(text="🗑 Удалить тренировку", callback_data=f"wt_del:{wt.id}")
    kb.button(text="⬅️ К списку", callback_data="wt_list")
    kb.adjust(1)
    return kb.as_markup()


def exercises_list_kb(exercises: list[Exercise], wt_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for ex in exercises:
        opt = " (опц.)" if ex.is_optional else ""
        if ex.kind == "strength":
            weight = f" · {format_weight(ex.weight_kg)}" if ex.weight_kg else ""
            text = f"🏋️ {ex.name}{opt} · {ex.sets}×{ex.reps}{weight}"
        else:
            text = f"🏃 {ex.name}{opt} · {format_duration(ex.duration_seconds)}"
        kb.button(text=text, callback_data=f"ex:{ex.id}")
    kb.button(text="➕ Добавить упражнение", callback_data=f"ex_new:{wt_id}")
    kb.button(text="⬅️ В меню тренировки", callback_data=f"wt:{wt_id}")
    kb.adjust(1)
    return kb.as_markup()


def exercise_card_kb(ex: Exercise) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"✏️ Название: {ex.name}", callback_data=f"ex_edit_name:{ex.id}")

    if ex.kind == "strength":
        kb.button(text=f"🔢 Подходы: {ex.sets}", callback_data=f"ex_edit_sets:{ex.id}")
        kb.button(text=f"🔁 Повторения: {ex.reps}", callback_data=f"ex_edit_reps:{ex.id}")
        weight_text = format_weight(ex.weight_kg)
        kb.button(text=f"⚖️ Вес: {weight_text}", callback_data=f"ex_edit_weight:{ex.id}")
    else:
        kb.button(
            text=f"⏱ Длительность: {format_duration(ex.duration_seconds)}",
            callback_data=f"ex_edit_duration:{ex.id}",
        )

    opt_text = "⚪ Опциональное: да" if ex.is_optional else "📌 Обязательное"
    kb.button(text=opt_text, callback_data=f"ex_toggle_opt:{ex.id}")
    kb.button(text="⬆️ Вверх", callback_data=f"ex_move_up:{ex.id}")
    kb.button(text="⬇️ Вниз", callback_data=f"ex_move_down:{ex.id}")
    kb.button(text="🗑 Убрать упражнение", callback_data=f"ex_del:{ex.id}")
    kb.button(text="⬅️ К списку", callback_data=f"wt_ex:{ex.workout_type_id}")
    kb.adjust(1)
    return kb.as_markup()


def confirm_delete_kb(ex_id: int, has_history: bool = False) -> InlineKeyboardMarkup:
    """Подтверждение удаления упражнения из справочника."""
    kb = InlineKeyboardBuilder()
    if has_history:
        kb.button(text="📦 Убрать в архив", callback_data=f"ex_del_yes:{ex_id}")
    else:
        kb.button(text="✅ Да, удалить", callback_data=f"ex_del_yes:{ex_id}")
    kb.button(text="❌ Отмена", callback_data=f"ex:{ex_id}")
    kb.adjust(1)
    return kb.as_markup()


def choose_kind_kb(wt_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏋️ Силовое (подходы, повторения, вес)",
              callback_data=f"ex_new_kind:strength:{wt_id}")
    kb.button(text="🏃 Кардио / разминка (длительность)",
              callback_data=f"ex_new_kind:cardio:{wt_id}")
    kb.button(text="⬅️ Отмена", callback_data=f"wt_ex:{wt_id}")
    kb.adjust(1)
    return kb.as_markup()


def confirm_workout_delete_kb(wt_id: int, has_history: bool) -> InlineKeyboardMarkup:
    """Подтверждение удаления тренировки.

    Если есть история — предлагаем выбор: архив или жёсткое удаление.
    Без истории — обычное удаление.
    """
    kb = InlineKeyboardBuilder()
    if has_history:
        kb.button(
            text="📦 Архивировать (история сохранится)",
            callback_data=f"wt_archive:{wt_id}",
        )
        kb.button(
            text="🔥 Удалить вместе с историей",
            callback_data=f"wt_del_yes:{wt_id}",
        )
    else:
        kb.button(text="✅ Да, удалить", callback_data=f"wt_del_yes:{wt_id}")
    kb.button(text="❌ Отмена", callback_data=f"wt_del_no:{wt_id}")
    kb.adjust(1)
    return kb.as_markup()


def training_list_kb(wt_id: int, session_id: int, exercises: list[Exercise],
                     sets_by_ex: dict, has_timer: bool = False,
                     optional_count: int = 0) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    sizes = []

    # Основной список: ТОЛЬКО обязательные упражнения
    main_exercises = [ex for ex in exercises if not ex.is_optional]
    for i, ex in enumerate(main_exercises, start=1):
        sets = sets_by_ex.get(ex.id, [])
        done_sets = sum(1 for s in sets if s.completed)
        plan_sets = (ex.sets or 0) if ex.kind == "strength" else 1

        if done_sets == 0:
            icon = "⚪"
        elif done_sets >= plan_sets:
            icon = "✅"
        else:
            icon = "🟡"

        kind_icon = "🏋️" if ex.kind == "strength" else "🏃"
        kb.button(text=f"{icon} {i}. {kind_icon} {ex.name}",
                  callback_data=f"tr_ex:{session_id}:{ex.id}")
        sizes.append(1)

    # Если есть опциональные — добавляем кнопку-папку
    if optional_count > 0:
        kb.button(text=f"⚪ Опциональные ({optional_count})",
                  callback_data=f"tr_opt_list:{session_id}")
        sizes.append(1)

    # Таймеры в ряд
    kb.button(text="⏱ 3 мин", callback_data=f"tr_timer:180:{session_id}:list")
    kb.button(text="⏱ Своё время",
              callback_data=f"tr_timer_custom:{session_id}:list")
    sizes.append(2)

    if has_timer:
        kb.button(text="⏹ Остановить таймер",
                  callback_data=f"tr_timer_stop:{session_id}:list")
        sizes.append(1)

    kb.button(text="🔄 Обновить время отдыха",
              callback_data=f"tr_refresh_list:{session_id}")
    sizes.append(1)

    kb.button(text="➕ Добавить упражнение",
              callback_data=f"tr_ex_add:{session_id}")
    sizes.append(1)
    kb.button(text="🗑 Убрать упражнение",
              callback_data=f"tr_remove_menu:{session_id}")
    sizes.append(1)
    kb.button(text="🏁 Завершить тренировку",
              callback_data=f"tr_finish:{session_id}")
    sizes.append(1)
    kb.button(text="⬅️ В меню тренировки", callback_data=f"wt:{wt_id}")
    sizes.append(1)

    kb.adjust(*sizes)
    return kb.as_markup()


def approach_kb(session_id: int, ex: Exercise, set_num: int,
                planned_reps: int | None, planned_weight: str | None,
                planned_duration: int | None,
                can_remove: bool = False,
                use_history: bool = False,
                is_first_set: bool = True,
                has_timer: bool = False) -> InlineKeyboardMarkup:  # <-- НОВЫЙ ПАРАМЕТР
    kb = InlineKeyboardBuilder()
    sizes = []

    if ex.kind == "strength":
        weight_text = format_weight(planned_weight)
        if use_history:
            if is_first_set:
                btn_text = f"✅ Как на прошлой тренировке: {planned_reps} × {weight_text}"
            else:
                btn_text = f"✅ Предыдущий подход: {planned_reps} × {weight_text}"
        else:
            btn_text = f"✅ Как планировал: {planned_reps} × {weight_text}"

        kb.button(text=btn_text,
                  callback_data=f"tr_save_planned:{session_id}:{ex.id}")
        sizes.append(1)
        kb.button(text="✏️ Ввести фактически",
                  callback_data=f"tr_custom:{session_id}:{ex.id}")
        sizes.append(1)
    else:
        from app.utils import format_duration
        duration_text = format_duration(planned_duration)
        btn_text = f"✅ Как на предыдущей тренировке: {duration_text}" if use_history else f"✅ Как планировал: {duration_text}"
        kb.button(text=btn_text,
                  callback_data=f"tr_save_planned:{session_id}:{ex.id}")
        sizes.append(1)
        kb.button(text="✏️ Ввести фактически",
                  callback_data=f"tr_custom:{session_id}:{ex.id}")
        sizes.append(1)

    if can_remove:
        kb.button(text="🗑 Убрать упражнение",
                  callback_data=f"tr_remove:{session_id}:{ex.id}")
        sizes.append(1)

    if ex.kind == "strength":
        kb.button(text="⏱ 60с",
                  callback_data=f"tr_timer:60:{session_id}:ex:{ex.id}")
        kb.button(text="⏱ 90с",
                  callback_data=f"tr_timer:90:{session_id}:ex:{ex.id}")
        kb.button(text="⏱ Своё время",
                  callback_data=f"tr_timer_custom:{session_id}:ex:{ex.id}")
        sizes.append(3)

        if has_timer:  # <-- КНОПКА ОСТАНОВКИ
            kb.button(text="⏹ Остановить таймер",
                      callback_data=f"tr_timer_stop:{session_id}:ex:{ex.id}")
            sizes.append(1)

        kb.button(text="🔄 Обновить время отдыха",
                  callback_data=f"tr_refresh:{session_id}:{ex.id}")
        sizes.append(1)

    kb.button(text="📝 Заметка",
              callback_data=f"tr_note_ex:{session_id}:{ex.id}")
    sizes.append(1)
    kb.button(text="⬅️ К списку упражнений",
              callback_data=f"tr_list:{session_id}")
    sizes.append(1)

    kb.adjust(*sizes)
    return kb.as_markup()


def finish_confirm_kb(session_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏁 Да, завершить", callback_data=f"tr_finish_yes:{session_id}")
    kb.button(text="▶️ Продолжить тренировку", callback_data=f"tr_list:{session_id}")
    kb.adjust(1)
    return kb.as_markup()


def cancel_kb() -> InlineKeyboardMarkup:
    """Универсальная кнопка отмены для любого FSM-диалога."""
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="fsm_cancel")
    return kb.as_markup()


def cardio_done_kb(session_id: int, ex: Exercise, can_remove: bool = False,
                   next_ex_id: int | None = None,
                   prev_ex_id: int | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    sizes = []

    kb.button(text="✏️ Изменить время",
              callback_data=f"tr_custom:{session_id}:{ex.id}")
    sizes.append(1)

    kb.button(text="📝 Заметка",
              callback_data=f"tr_note_ex:{session_id}:{ex.id}")
    sizes.append(1)

    if can_remove:
        kb.button(text="🗑 Убрать упражнение",
                  callback_data=f"tr_remove:{session_id}:{ex.id}")
        sizes.append(1)

    # Навигация (в один ряд)
    nav_count = 0
    if prev_ex_id:
        kb.button(text="⬅️ Предыдущее",
                  callback_data=f"tr_ex:{session_id}:{prev_ex_id}")
        nav_count += 1
    if next_ex_id:
        kb.button(text="Следующее ➡️",
                  callback_data=f"tr_ex:{session_id}:{next_ex_id}")
        nav_count += 1

    if nav_count > 0:
        sizes.append(nav_count)

    kb.button(text="⬅️ К списку упражнений",
              callback_data=f"tr_list:{session_id}")
    sizes.append(1)

    kb.adjust(*sizes)
    return kb.as_markup()


def strength_summary_kb(session_id: int, ex: Exercise, sets: list,
                        next_ex_id: int | None = None,
                        prev_ex_id: int | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    sizes = []

    # 1. Группируем подходы (максимум по 2 в ряд)
    for s in sets:
        weight_text = format_weight(s.weight_kg)
        kb.button(
            text=f"✏️ {s.set_number}. {s.reps}×{weight_text}",
            callback_data=f"tr_edit_set:{session_id}:{s.id}",
        )

    # Вычисляем, сколько кнопок в каждом ряду для подходов
    num_sets = len(sets)
    while num_sets > 0:
        row_size = min(num_sets, 2)
        sizes.append(row_size)
        num_sets -= row_size

    # 2. Основные действия
    kb.button(text="➕ Добавить подход",
              callback_data=f"tr_add_set:{session_id}:{ex.id}")
    sizes.append(1)

    kb.button(text="📝 Заметка",
              callback_data=f"tr_note_ex:{session_id}:{ex.id}")
    sizes.append(1)

    # 3. Навигация (в один ряд)
    nav_count = 0
    if prev_ex_id:
        kb.button(text="⬅️ Предыдущее",
                  callback_data=f"tr_ex:{session_id}:{prev_ex_id}")
        nav_count += 1
    if next_ex_id:
        kb.button(text="Следующее ➡️",
                  callback_data=f"tr_ex:{session_id}:{next_ex_id}")
        nav_count += 1

    if nav_count > 0:
        sizes.append(nav_count)

    # 4. Выход в список
    kb.button(text="⬅️ К списку упражнений",
              callback_data=f"tr_list:{session_id}")
    sizes.append(1)

    # Применяем настройки рядов
    kb.adjust(*sizes)
    return kb.as_markup()


def training_remove_menu_kb(session_id: int, removable: list[Exercise]) -> InlineKeyboardMarkup:
    """Список упражнений, которые можно убрать из шаблона прямо из тренировки."""
    kb = InlineKeyboardBuilder()
    for ex in removable:
        kb.button(
            text=f"🗑 {ex.name}",
            callback_data=f"tr_remove:{session_id}:{ex.id}:menu",
        )
    kb.button(text="⬅️ Назад в тренировку", callback_data=f"tr_list:{session_id}")
    kb.adjust(1)
    return kb.as_markup()


def after_finish_kb() -> InlineKeyboardMarkup:
    """Кнопки после завершения тренировки."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🏋️ В меню тренировок", callback_data="wt_list")
    return kb.as_markup()


def archive_list_kb(grouped_exercises: list[tuple[Exercise, int]],
                    wt_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for ex, count in grouped_exercises:
        kind_icon = "🏋️" if ex.kind == "strength" else "🏃"
        if ex.kind == "strength":
            weight = f" · {format_weight(ex.weight_kg)}" if ex.weight_kg else ""
            text = f"📦 {kind_icon} {ex.name} ({ex.sets}×{ex.reps}{weight})"
        else:
            text = f"📦 {kind_icon} {ex.name} (кардио)"

        if count > 1:
            text += f" [x{count}]"

        kb.button(text=text, callback_data=f"ex_arch_view:{ex.id}")

    kb.button(text="⬅️ В меню тренировки", callback_data=f"wt:{wt_id}")
    kb.adjust(1)
    return kb.as_markup()


def archive_card_kb(ex: Exercise, has_conflict: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if has_conflict:
        kb.button(text="🔗 Объединить и восстановить", callback_data=f"ex_restore_merge:{ex.id}")
    else:
        kb.button(text="🔄 Восстановить", callback_data=f"ex_restore_merge:{ex.id}")
    kb.button(text="🔥 Удалить навсегда",
                  callback_data=f"ex_arch_del_ask:{ex.id}")
    kb.button(text="⬅️ К архиву", callback_data=f"ex_arch_menu:{ex.workout_type_id}")
    kb.adjust(1)
    return kb.as_markup()


def note_edit_kb(session_id: int, ex_id: int, has_note: bool) -> InlineKeyboardMarkup:
    """Клавиатура для экрана ввода заметки."""
    kb = InlineKeyboardBuilder()
    if has_note:
        kb.button(text="🗑 Удалить заметку", callback_data=f"tr_note_del:{session_id}:{ex_id}")
    kb.button(text="❌ Отмена", callback_data=f"tr_ex:{session_id}:{ex_id}")
    kb.adjust(1)
    return kb.as_markup()


def confirm_training_delete_kb(session_id: int, ex_id: int, context: str,
                               has_history: bool) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения удаления упражнения из активной тренировки."""
    kb = InlineKeyboardBuilder()
    if has_history:
        kb.button(text="📦 Убрать в архив",
                  callback_data=f"tr_remove_yes:{session_id}:{ex_id}:{context}")
    else:
        kb.button(text="✅ Да, удалить",
                  callback_data=f"tr_remove_yes:{session_id}:{ex_id}:{context}")

    if context == "menu":
        kb.button(text="❌ Отмена",
                  callback_data=f"tr_remove_menu:{session_id}")
    else:
        kb.button(text="❌ Отмена", callback_data=f"tr_ex:{session_id}:{ex_id}")
    kb.adjust(1)
    return kb.as_markup()


def confirm_archive_delete_kb(ex_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔥 Да, удалить навсегда", callback_data=f"ex_arch_del_yes:{ex_id}")
    kb.button(text="❌ Отмена", callback_data=f"ex_arch_view:{ex_id}")
    kb.adjust(1)
    return kb.as_markup()


def workout_description_kb() -> InlineKeyboardMarkup:
    """Клавиатура при создании тренировки (шаг с описанием)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="⏭ Пропустить", callback_data="wt_desc_skip")
    kb.button(text="❌ Отмена", callback_data="fsm_cancel")
    kb.adjust(1)
    return kb.as_markup()


def workouts_archive_list_kb(workouts: list[WorkoutType]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for w in workouts:
        kb.button(text=f"📦 {w.name}", callback_data=f"wt_arch_view:{w.id}")
    kb.button(text="⬅️ Назад к тренировкам", callback_data="wt_list")
    kb.adjust(1)
    return kb.as_markup()


def archived_workout_card_kb(wt_id: int, has_conflict: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if has_conflict:
        kb.button(text="🔗 Объединить и восстановить", callback_data=f"wt_merge:{wt_id}")
    else:
        kb.button(text="🔄 Восстановить", callback_data=f"wt_restore:{wt_id}")
    kb.button(text="🔥 Удалить навсегда", callback_data=f"wt_arch_del_ask:{wt_id}")
    kb.button(text="⬅️ К архиву", callback_data="wt_arch_list")
    kb.adjust(1)
    return kb.as_markup()


def confirm_duplicate_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, добавить", callback_data="dup_confirm")
    kb.button(text="❌ Отмена", callback_data="dup_cancel")
    kb.adjust(2)
    return kb.as_markup()


def edit_set_kb(session_id: int, set_id: int, can_delete: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура для экрана редактирования подхода."""
    kb = InlineKeyboardBuilder()
    if can_delete:
        kb.button(text="🗑 Удалить подход", callback_data=f"tr_delete_set:{session_id}:{set_id}")
    kb.button(text="❌ Отмена", callback_data="fsm_cancel")
    kb.adjust(1)
    return kb.as_markup()


def optional_list_kb(session_id: int, exercises: list[Exercise],
                     sets_by_ex: dict) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i, ex in enumerate(exercises, start=1):
        sets = sets_by_ex.get(ex.id, [])
        done_sets = sum(1 for s in sets if s.completed)
        plan_sets = (ex.sets or 0) if ex.kind == "strength" else 1

        if done_sets == 0:
            icon = "⚪"
        elif done_sets >= plan_sets:
            icon = "✅"
        else:
            icon = "🟡"

        kind_icon = "🏋️" if ex.kind == "strength" else "🏃"
        kb.button(text=f"{icon} {i}. {kind_icon} {ex.name}",
                  callback_data=f"tr_ex:{session_id}:{ex.id}")
        kb.adjust(1)

    kb.button(text="⬅️ К основной тренировке",
              callback_data=f"tr_list:{session_id}")
    kb.adjust(1)
    return kb.as_markup()


def main_reply_kb() -> ReplyKeyboardMarkup:
    """Постоянная клавиатура внизу экрана."""
    kb = ReplyKeyboardBuilder()
    kb.button(text="🏠 Главная")
    kb.adjust(1)
    return kb.as_markup(resize_keyboard=True)


def start_inline_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="ℹ️ Справка", callback_data="show_help")
    return kb.as_markup()
