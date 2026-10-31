"""Формирование текста карточек."""
from datetime import datetime
from app.db.models import Exercise, WorkoutType
from app.utils import format_duration, format_weight


def render_workout_card(wt: WorkoutType) -> str:
    """Карточка тренировки. Описание показываем только если есть."""
    text = f"🏋️ <b>{wt.name}</b>"
    if wt.description:
        text += f"\n\n{wt.description}"
    return text


def render_exercise_card(ex: Exercise) -> str:
    opt = " <i>(опциональное)</i>" if ex.is_optional else ""

    if ex.kind == "strength":
        weight = format_weight(ex.weight_kg)
        return (
            f"<b>{ex.name}</b>{opt}\n\n"
            f"🔢 Подходы: <b>{ex.sets}</b>\n"
            f"🔁 Повторения: <b>{ex.reps}</b>\n"
            f"⚖️ Вес: <b>{weight}</b>"
        )
    return (
        f"<b>{ex.name}</b>{opt}\n\n"
        f"⏱ Длительность: <b>{format_duration(ex.duration_seconds)}</b>"
    )


def render_training_list(wt: WorkoutType, exercises: list[Exercise],
                         sets_by_ex: dict, session_started: datetime) -> str:
    """Текст экрана активной тренировки. Кардио показывает фактическое время."""
    from app.utils import fmt_msk_datetime, format_duration

    lines = [
        f"🏋️ <b>{wt.name}</b>",
        f"⏱ Начата: {fmt_msk_datetime(session_started)} (МСК)",
        "",
    ]

    done_ex = 0
    total_ex = 0

    for i, ex in enumerate(exercises, start=1):
        sets = sets_by_ex.get(ex.id, [])
        done_sets = sum(1 for s in sets if s.completed)
        plan_sets = (ex.sets or 0) if ex.kind == "strength" else 1
        is_done = done_sets >= plan_sets

        if done_sets == 0:
            icon = "⚪"
        elif is_done:
            icon = "✅"
        else:
            icon = "🟡"

        opt = " <i>(опц.)</i>" if ex.is_optional else ""

        if ex.kind == "strength":
            progress = f"{done_sets}/{plan_sets}"
        else:
            # кардио — показываем фактическую длительность
            completed = [s for s in sets if s.completed]
            if completed and completed[0].duration_seconds:
                progress = format_duration(completed[0].duration_seconds)
            elif completed:
                progress = "✓"
            else:
                progress = "—"

        lines.append(f"{icon} {i}. <b>{ex.name}</b>{opt} — {progress}")

        if not ex.is_optional or done_sets > 0:
            total_ex += 1
        if is_done:
            done_ex += 1

    lines.append("")
    lines.append(f"📊 Выполнено: <b>{done_ex} / {total_ex}</b> упражнений")
    return "\n".join(lines)


def render_approach(ex: Exercise, set_num: int, planned_reps: int | None,
                    planned_weight: str | None, planned_duration: int | None,
                    last_reps: int | None = None,
                    last_weight: str | None = None,
                    last_note: str | None = None,
                    last_duration: int | None = None) -> str:  # <--- НОВЫЙ ПАРАМЕТР
    from app.utils import format_duration

    if ex.kind == "strength":
        if last_reps or last_weight:
            display_reps = last_reps if last_reps else planned_reps
            display_weight = format_weight(
                last_weight if last_weight else planned_weight)
            header = f"Предыдущая тренировка: <b>{display_reps} × {display_weight}</b>"
        else:
            display_reps = planned_reps
            display_weight = format_weight(planned_weight)
            header = f"План: <b>{display_reps} × {display_weight}</b>"

        if last_note:
            header += f"\n📝 <i>Заметка из предыдущей тренировки: {last_note}</i>"

        return (
            f"<b>{ex.name}</b>\n\n"
            f"Подход <b>{set_num}</b> из {ex.sets}\n"
            f"{header}"
        )

    # ─── КАРДИО ───
    # Если есть прошлое время, показываем его, иначе — план
    if last_duration:
        duration_header = f"Прошлый раз: <b>{format_duration(last_duration)}</b>"
    else:
        duration_header = f"План: <b>{format_duration(planned_duration)}</b>"

    note_text = f"\n\n📝 <i>Заметка из предыдущей тренировки: {last_note}</i>" if last_note else ""

    return (
        f"<b>{ex.name}</b>\n\n"
        f"{duration_header}{note_text}"
    )


def render_strength_summary(ex: Exercise, sets: list) -> str:
    """Экран итогов силового упражнения.

    Показывает все подходы + суммарные повторы + тоннаж (reps × weight).
    Тоннаж — простая метрика прогресса: если растёт от тренировки к тренировке,
    значит становишься сильнее.
    """
    lines = [f"<b>{ex.name}</b>", ""]

    if not sets:
        lines.append("Пока нет подходов.")
        return "\n".join(lines)

    total_reps = 0
    total_volume = 0.0
    for s in sets:
        reps = s.reps or 0
        # Безопасно парсим вес
        try:
            weight = float(s.weight_kg) if s.weight_kg else 0.0
        except ValueError:
            weight = 0.0  # если там текст, тоннаж не считаем

        weight_text = format_weight(s.weight_kg)
        lines.append(f"{s.set_number}. {reps} × {weight_text}")
        total_reps += reps
        total_volume += reps * weight

    lines.append("")
    lines.append(f"📊 Всего повторов: <b>{total_reps}</b>")
    if total_volume > 0:
        lines.append(f"⚖️ Тоннаж: <b>{total_volume:g} кг</b>")

    return "\n".join(lines)
