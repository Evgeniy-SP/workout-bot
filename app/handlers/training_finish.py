"""Хэндлеры для завершения тренировки и управления упражнениями на ходу."""
import random
from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy import delete, func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Exercise, SessionExerciseNote, SessionSet, WorkoutSession
from app.db.queries import get_sets_grouped
from app.keyboards.workout_kb import (
    after_finish_kb, choose_kind_kb, confirm_training_delete_kb,
    finish_confirm_kb, training_remove_menu_kb,
)
from app.services.training_service import (
    load_workout, render_approach_screen, render_list,
)
from app.states import WorkoutCreate

router = Router()


# ═══════════════════════════════════════════════════════════
#  Обновление времени отдыха
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("tr_refresh:"))
async def cb_refresh_approach(callback: CallbackQuery, session: AsyncSession):
    _, sess_str, ex_str = callback.data.split(":")
    session_id = int(sess_str)
    ex_id = int(ex_str)

    result = await render_approach_screen(session, session_id, ex_id)
    if result:
        text, kb = result
        try:
            await callback.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass
    await callback.answer("Время обновлено")


@router.callback_query(F.data.startswith("tr_refresh_list:"))
async def cb_refresh_list(callback: CallbackQuery, session: AsyncSession):
    session_id = int(callback.data.split(":")[1])
    ws = await session.get(WorkoutSession, session_id)
    if not ws:
        return await callback.answer("Не найдено", show_alert=True)

    text, kb = await render_list(session, session_id, ws.user_id)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await callback.answer("Время обновлено")


# ═══════════════════════════════════════════════════════════
#  Добавление упражнения во время тренировки
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("tr_ex_add:"))
async def cb_training_add_ex(callback: CallbackQuery, session: AsyncSession,
                             state: FSMContext):
    session_id = int(callback.data.split(":")[1])
    ws = await session.get(WorkoutSession, session_id)
    if not ws or ws.finished_at:
        return await callback.answer("Тренировка не активна", show_alert=True)

    await state.update_data(
        wt_id=ws.workout_type_id,
        return_to_session=session_id,
        return_to="tr_list",
    )
    await state.set_state(WorkoutCreate.adding_exercise_kind)
    await callback.message.edit_text(
        "Какой тип упражнения?",
        reply_markup=choose_kind_kb(ws.workout_type_id)
    )
    await callback.answer()


# ═══════════════════════════════════════════════════════════
#  Удаление упражнения из шаблона (на ходу)
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("tr_remove:"))
async def cb_training_remove_ask(callback: CallbackQuery,
                                 session: AsyncSession):
    parts = callback.data.split(":")
    session_id = int(parts[1])
    ex_id = int(parts[2])
    from_menu = len(parts) > 3 and parts[3] == "menu"
    context = "menu" if from_menu else "card"

    ws = await session.get(WorkoutSession, session_id)
    ex = await session.get(Exercise, ex_id)
    if not ws or not ex or ws.finished_at:
        return await callback.answer("Недоступно", show_alert=True)

    current_sets = (await get_sets_grouped(session, session_id)).get(ex_id, [])
    if current_sets:
        return await callback.answer(
            "По упражнению уже есть подходы в этой тренировке. Используйте «⏭ Пропустить».",
            show_alert=True,
        )

    history_count = await session.scalar(
        select(sa_func.count()).select_from(SessionSet).where(
            SessionSet.exercise_id == ex_id)
    ) or 0

    if history_count > 0:
        text = (
            f"Убрать упражнение <b>{ex.name}</b> из шаблона?\n\n"
            f"Упражнение выполнялось в <b>{history_count}</b> "
            f"тренировк{'е' if history_count == 1 else 'ах'} — история сохранится.\n\n"
            "📦 Упражнение скроется из шаблона."
        )
    else:
        text = (
            f"Удалить упражнение <b>{ex.name}</b>?\n\n"
            "Истории нет — удалится полностью."
        )
    await callback.message.edit_text(
        text,
        reply_markup=confirm_training_delete_kb(session_id, ex_id, context,
                                                history_count > 0)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tr_remove_yes:"))
async def cb_training_remove_confirm(callback: CallbackQuery,
                                     session: AsyncSession):
    parts = callback.data.split(":")
    session_id = int(parts[1])
    ex_id = int(parts[2])
    from_menu = len(parts) > 3 and parts[3] == "menu"

    ws = await session.get(WorkoutSession, session_id)
    ex = await session.get(Exercise, ex_id)
    if not ws or not ex or ws.finished_at:
        return await callback.answer("Недоступно", show_alert=True)

    name = ex.name
    history_count = await session.scalar(
        select(sa_func.count()).select_from(SessionSet).where(
            SessionSet.exercise_id == ex_id)
    ) or 0

    if history_count > 0:
        ex.is_archived = True
        await session.commit()
        action = "📦 Убрано в архив (история сохранена)"
    else:
        await session.delete(ex)
        await session.commit()
        action = "🗑 Удалено"

    if from_menu:
        wt = await load_workout(session, ws.workout_type_id)
        sets_by_ex = await get_sets_grouped(session, session_id)
        removable = [e for e in wt.exercises if not sets_by_ex.get(e.id)]

        if removable:
            await callback.message.edit_text(
                f"{action}: <b>{name}</b>\n\nМожно убрать ещё:",
                reply_markup=training_remove_menu_kb(session_id, removable),
            )
        else:
            text, kb = await render_list(session, session_id, ws.user_id)
            await callback.message.edit_text(
                f"{action}: <b>{name}</b>\n\n" + text, reply_markup=kb
            )
        await callback.answer("Готово")
        return

    text, kb = await render_list(session, session_id, ws.user_id)
    await callback.message.edit_text(
        f"{action}: <b>{name}</b>\n\n" + text, reply_markup=kb
    )
    await callback.answer("Готово")


@router.callback_query(F.data.startswith("tr_remove_menu:"))
async def cb_training_remove_menu(callback: CallbackQuery,
                                  session: AsyncSession):
    session_id = int(callback.data.split(":")[1])
    ws = await session.get(WorkoutSession, session_id)
    if not ws or ws.finished_at:
        return await callback.answer("Тренировка не активна", show_alert=True)

    wt = await load_workout(session, ws.workout_type_id)
    sets_by_ex = await get_sets_grouped(session, session_id)

    removable = [ex for ex in wt.exercises if not sets_by_ex.get(ex.id)]

    if not removable:
        text, kb = await render_list(session, session_id, ws.user_id)
        reason = (
            "Все упражнения уже начаты в этой тренировке."
            if wt.exercises
            else "В тренировке нет упражнений."
        )
        await callback.message.edit_text(f"{reason}\n\n" + text,
                                         reply_markup=kb)
        return await callback.answer()

    await callback.message.edit_text(
        "🗑 <b>Убрать упражнение из шаблона</b>\n\n"
        "Оно пропадёт из этой и будущих тренировок. "
        "Если есть история выполнения — она сохранится.\n\n"
        "Если просто хочешь пропустить сейчас — вернись и нажми на упражнение → «⏭ Пропустить».",
        reply_markup=training_remove_menu_kb(session_id, removable),
    )
    await callback.answer()


# ═══════════════════════════════════════════════════════════
#  Завершение тренировки
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("tr_finish:"))
async def cb_finish_ask(callback: CallbackQuery, session: AsyncSession):
    session_id = int(callback.data.split(":")[1])
    ws = await session.get(WorkoutSession, session_id)
    if not ws:
        return await callback.answer("Не найдено", show_alert=True)

    wt = await load_workout(session, ws.workout_type_id)
    sets_by_ex = await get_sets_grouped(session, session_id)

    total_ex = 0
    not_done = 0
    for ex in wt.exercises:
        sets = sets_by_ex.get(ex.id, [])
        done = sum(1 for s in sets if s.completed)
        plan = (ex.sets or 0) if ex.kind == "strength" else 1
        is_done = done >= plan

        if not ex.is_optional or done > 0:
            total_ex += 1
            if not is_done:
                not_done += 1

    if not_done > 0:
        text = (
            f"🏁 <b>Завершить тренировку?</b>\n\n"
            f"⚠️ Не выполнено: <b>{not_done} из {total_ex}</b> упражнений.\n\n"
            "Тренировка сохранится в истории, но по этим упражнениям "
            "не будет записано ни одного подхода.\n\n"
            "Точно завершить?"
        )
    else:
        text = (
            "🏁 <b>Завершить тренировку?</b>\n\n"
            "✅ Все упражнения выполнены. Отличная работа!"
        )

    await callback.message.edit_text(text, reply_markup=finish_confirm_kb(
        session_id))
    await callback.answer()


@router.callback_query(F.data.startswith("tr_finish_yes:"))
async def cb_finish_confirm(callback: CallbackQuery, session: AsyncSession,
                            state: FSMContext):
    await state.clear()
    session_id = int(callback.data.split(":")[1])
    ws = await session.get(WorkoutSession, session_id)
    if not ws:
        return await callback.answer("Не найдено", show_alert=True)

    ws.finished_at = datetime.now(timezone.utc)
    await session.commit()

    wt = await load_workout(session, ws.workout_type_id)
    sets_by_ex = await get_sets_grouped(session, session_id)

    total_ex = 0
    done_ex = 0
    for ex in wt.exercises:
        sets = sets_by_ex.get(ex.id, [])
        done = sum(1 for s in sets if s.completed)
        plan = (ex.sets or 0) if ex.kind == "strength" else 1
        is_done = done >= plan

        if not ex.is_optional or done > 0:
            total_ex += 1
        if is_done:
            done_ex += 1

    ratio = done_ex / total_ex if total_ex else 0

    duration_sec = int((ws.finished_at - ws.started_at).total_seconds())
    minutes = duration_sec // 60

    lines = [
        f"🏁 <b>{wt.name}</b> — завершена!",
        "",
        f"⏱ Длительность: ~{minutes} мин",
        f"📊 Выполнено: {done_ex} из {total_ex} упражнений",
        "",
    ]

    # Текстовый цикл (для красивого вывода в сообщении)
    for ex in wt.exercises:
        sets = sets_by_ex.get(ex.id, [])
        done = sum(1 for s in sets if s.completed)
        plan = (ex.sets or 0) if ex.kind == "strength" else 1
        is_done = done >= plan

        opt_mark = " <i>(опц.)</i>" if ex.is_optional else ""

        # Если упражнение опциональное и НЕ сделано (0 подходов) — вообще не выводим его
        if ex.is_optional and done == 0:
            continue

        if is_done:
            lines.append(f"✅ {ex.name}{opt_mark}")
        elif done > 0:
            lines.append(f"🟡 {ex.name}{opt_mark}: {done}/{plan}")
        else:
            # Сюда попадут только обязательные, которые пропущены
            lines.append(f"⚪ {ex.name}")

    if ratio >= 1.0:
        phrases = [
            "🏆 Идеальная тренировка! Все упражнения выполнены.",
            "🔥 Ты на пике формы! 100% выполнения.",
            "💎 Безупречно! Так держать.",
        ]
    elif ratio >= 0.7:
        phrases = [
            "💪 Отличная работа! Большая часть программы сделана.",
            "🔥 Хороший результат — прогресс налицо.",
            "👊 Ты выложился! Продолжай в том же духе.",
        ]
    elif ratio >= 0.4:
        phrases = [
            "👍 Хорошо поработал! Каждый подход важен.",
            "📈 Ты движешься вперёд. Не останавливайся.",
            "💡 Половина пути пройдена — продолжай!",
        ]
    else:
        phrases = [
            "🌱 Главное — не сдаваться. Каждый шаг важен.",
            "🚶 Лучше что-то, чем ничего. Ты начал!",
            "⏳ Сегодня так, завтра — больше. Главное — регулярность.",
        ]

    lines.append("")
    lines.append(f"<i>{random.choice(phrases)}</i>")

    await callback.message.edit_text("\n".join(lines),
                                     reply_markup=after_finish_kb())
    await callback.answer("Тренировка завершена")
