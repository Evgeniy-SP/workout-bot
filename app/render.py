"""Формирование текста карточек."""
import random
from datetime import datetime

from app.db.models import Exercise, WorkoutType
from app.utils import format_duration, format_weight


def render_workout_card(wt: WorkoutType) -> str:
    """Карточка тренировки."""
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


def render_training_list(wt: WorkoutType, all_exercises: list[Exercise],
                         visible_exercises: list[Exercise],
                         sets_by_ex: dict, session_started: datetime,
                         rest_time_str: str | None = None,
                         timer_str: str | None = None,
                         last_exercise_name: str | None = None,
                         session_note: str | None = None) -> str:
    from app.utils import fmt_msk_datetime, format_duration

    # 1. Красивая шапка
    lines = [
        f"⚡ <b>Тренировка: {wt.name}</b>",
        f"<i>Начата: {fmt_msk_datetime(session_started)} (МСК)</i>\n",
    ]

    if session_note:
        lines.append(f"📝 <i>{session_note}</i>\n")

    # 1. Считаем прогресс по ВСЕМ упражнениям (включая опциональные)
    done_ex = 0
    total_ex = 0
    for ex in all_exercises:
        sets = sets_by_ex.get(ex.id, [])
        done_sets = sum(1 for s in sets if s.completed)
        plan_sets = (ex.sets or 0) if ex.kind == "strength" else 1
        is_done = done_sets >= plan_sets

        if not ex.is_optional or done_sets > 0:
            total_ex += 1
        if is_done:
            done_ex += 1

    # 2. Выводим в список ТОЛЬКО видимые (обязательные) упражнения
    for i, ex in enumerate(visible_exercises, start=1):
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
            completed = [s for s in sets if s.completed]
            if completed and completed[0].duration_seconds:
                progress = format_duration(completed[0].duration_seconds)
            elif completed:
                progress = "✓"
            else:
                progress = "—"

        lines.append(f"{icon} {i}. <b>{ex.name}</b>{opt} — {progress}")

    lines.append("")

    # Блок таймеров/отдыха (единый стиль)
    if timer_str:
        lines.append(f"⏱ <b>Таймер:</b> {timer_str}")
    if rest_time_str:
        if last_exercise_name:
            lines.append(f"⏱ <b>Отдых после «{last_exercise_name}»:</b> {rest_time_str}")
        else:
            lines.append(f"⏱ <b>Отдых:</b> {rest_time_str}")

    # 3. Красивый блок с прогрессом (в цитате)
    lines.append(
        f"<blockquote>📊 Выполнено: <b>{done_ex} / {total_ex}</b> упражнений</blockquote>")

    return "\n".join(lines)


def render_approach(ex: Exercise, set_num: int, planned_reps: int | None,
                    planned_weight: str | None, planned_duration: int | None,
                    last_reps: int | None = None,
                    last_weight: str | None = None,
                    last_note: str | None = None,
                    last_duration: int | None = None,
                    rest_time_str: str | None = None,
                    timer_str: str | None = None) -> str:
    from app.utils import format_duration

    if ex.kind == "strength":
        # 1. Формируем блок истории/плана
        if last_reps or last_weight:
            display_reps = last_reps if last_reps else planned_reps
            display_weight = format_weight(
                last_weight if last_weight else planned_weight)
            history_text = f"🕰 <b>Прошлый раз: {display_reps} × {display_weight}</b>"
        else:
            display_reps = planned_reps
            display_weight = format_weight(planned_weight)
            history_text = f"📋 <b>План: {display_reps} × {display_weight}</b>"

        if last_note:
            history_text += f"\n📝 <i>{last_note}</i>"

        # 2. Собираем всё в красивую цитату
        done_sets = set_num - 1
        blockquote = (
            f"<blockquote>"
            f"📈 Выполнено: <b>{done_sets}</b> из <b>{ex.sets}</b>\n"
            f"📍 Текущий: <b>Подход {set_num}</b>\n"
            f"{history_text}"
            f"</blockquote>"
        )

        # 3. Дополнительный блок (таймер и отдых)
        extra = ""
        if timer_str:
            extra += f"\n⏱ <b>Таймер:</b> {timer_str}"
        if rest_time_str:
            extra += f"\n⏱ <i>Отдых: {rest_time_str}</i>"

        return (
            f"🏋️ <b>{ex.name}</b>\n\n"
            f"{blockquote}"
            f"{extra}"
        )

    # ─── КАРДИО ───
    if last_duration:
        duration_header = f"🕰 <b>Прошлый раз: {format_duration(last_duration)}</b>"
    else:
        duration_header = f"📋 <b>План: {format_duration(planned_duration)}</b>"

    note_text = f"\n📝 <i>{last_note}</i>" if last_note else ""

    blockquote = f"<blockquote>{duration_header}{note_text}</blockquote>"

    return (
        f"🏃 <b>{ex.name}</b>\n\n"
        f"{blockquote}"
    )

def render_strength_summary(ex: Exercise, sets: list) -> str:
    if not sets:
        return f"🏋️ <b>{ex.name}</b>\n\nПока нет подходов."

    phrases = [
        "🎉 <b>Отлично! Упражнение выполнено!</b>",
        "💪 <b>Красавчик! Все подходы сделаны!</b>",
        "🔥 <b>Так держать! Упражнение закрыто!</b>",
        "🚀 <b>Мощно! Едем дальше!</b>",
        "🏆 <b>Победа! Подходы выполнены!</b>"
    ]
    congrats = random.choice(phrases)

    total_reps = 0
    total_volume = 0.0
    for s in sets:
        reps = s.reps or 0
        try:
            weight = float(s.weight_kg) if s.weight_kg else 0.0
        except ValueError:
            weight = 0.0
        total_reps += reps
        total_volume += reps * weight

    # 1. Сначала заголовок и список подходов
    lines = [
        f"🏋️ <b>{ex.name}</b>\n",
        f"{congrats}\n",
        "📋 <b>Выполненные подходы:</b>"
    ]

    for s in sets:
        reps = s.reps or 0
        weight_text = format_weight(s.weight_kg)
        # Добавили галочку и жирный шрифт для красоты
        lines.append(f"✅ <b>{s.set_number}.</b> {reps} × <b>{weight_text}</b>")

    # 2. В самом низу — красивая цитата со статистикой
    stats = f"<blockquote>📈 Всего повторов: <b>{total_reps}</b>"
    if total_volume > 0:
        stats += f"\n⚖️ Тоннаж: <b>{total_volume:g} кг</b>"
    stats += "</blockquote>"

    lines.append(f"\n{stats}")

    lines.append("\n💡 <i>Нажми на подход, чтобы изменить его, или добавь новый.</i>")
    return "\n".join(lines)
