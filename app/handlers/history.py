"""Хэндлеры для раздела «История тренировок»."""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.queries import get_user_sessions, get_user_sessions_count, get_session_details
from app.keyboards.workout_kb import history_list_kb, history_details_kb
from app.render import render_history_details
from app.services.training_service import get_user

router = Router()


async def _render_history_page(
    session: AsyncSession, user_id: int, page: int, message: Message, is_edit: bool = True
):
    """Вспомогательная функция: собирает данные и отрисовывает страницу истории."""
    limit = 5
    offset = page * limit

    sessions = await get_user_sessions(session, user_id, offset, limit)
    total_count = await get_user_sessions_count(session, user_id)

    if not sessions and page > 0:
        return False # Если пусто, сообщаем вызвавшему, что страницы нет

    has_next = (offset + limit) < total_count

    if not sessions:
        text = "📊 <b>История тренировок</b>\n\nУ тебя пока нет завершенных тренировок."
        kb = history_list_kb([], 0, False)
    else:
        total_pages = (total_count - 1) // limit + 1
        text = (
            f"📊 <b>История твоих тренировок</b>\n\n"
            f"Страница {page + 1} из {total_pages}\n\n"
            f"👇 Выбери тренировку для просмотра деталей:"
        )
        kb = history_list_kb(sessions, page, has_next)

    if is_edit:
        try:
            await message.edit_text(text, reply_markup=kb)
        except Exception:
            pass
    else:
        await message.answer(text, reply_markup=kb)

    return True


@router.callback_query(F.data.startswith("hist_page:"))
async def cb_history_page(callback: CallbackQuery, session: AsyncSession):
    page = int(callback.data.split(":")[1])

    user = await get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Сначала /start", show_alert=True)

    success = await _render_history_page(session, user.id, page, callback.message, is_edit=True)
    if not success:
        await callback.answer("Это последняя страница", show_alert=True)
    else:
        await callback.answer()


@router.message(F.text == "📊 История")
async def cmd_history(message: Message, session: AsyncSession):
    """Хэндлер для нижней кнопки 'История'."""
    user = await get_user(session, message.from_user.id)
    if not user:
        return await message.answer("Сначала нажми /start")

    await _render_history_page(session, user.id, 0, message, is_edit=False)


@router.callback_query(F.data.startswith("hist_view:"))
async def cb_history_view(callback: CallbackQuery, session: AsyncSession):
    """Просмотр деталей конкретной тренировки."""
    parts = callback.data.split(":")
    session_id = int(parts[1])
    page = int(parts[2])

    ws = await get_session_details(session, session_id)
    if not ws:
        return await callback.answer("Тренировка не найдена", show_alert=True)

    text = render_history_details(ws)

    # Собираем клавиатуру с упражнениями
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()

    unique_exercises = {}
    for s in ws.sets:
        if s.completed and s.exercise:
            unique_exercises[s.exercise.id] = s.exercise.name

    for ex_id, ex_name in unique_exercises.items():
        kb.button(text=f"📈 {ex_name}",
                  callback_data=f"ex_progress:{ex_id}:{session_id}:{page}")

    kb.button(text="⬅️ Назад к истории", callback_data=f"hist_page:{page}")
    kb.adjust(1)

    # УДАЛЯЕМ СТАРОЕ СООБЩЕНИЕ (с фото) И ОТПРАВЛЯЕМ НОВОЕ
    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(text, reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("ex_progress:"))
async def cb_exercise_progress(callback: CallbackQuery, session: AsyncSession):
    """Показывает график прогресса и личные рекорды."""
    parts = callback.data.split(":")
    ex_id = int(parts[1])
    session_id = int(parts[2])
    page = int(parts[3])

    from app.db.models import Exercise
    from app.db.queries import get_exercise_history
    from app.services.training_service import calculate_personal_records, get_user
    from app.services.chart_service import generate_progress_chart
    from app.keyboards.workout_kb import exercise_progress_kb
    from aiogram.types import BufferedInputFile
    import asyncio
    import re
    from collections import defaultdict
    from datetime import datetime, time

    ex = await session.get(Exercise, ex_id)
    if not ex:
        return await callback.answer("Упражнение не найдено", show_alert=True)

    # ПОЛУЧАЕМ ПОЛЬЗОВАТЕЛЯ
    user = await get_user(session, callback.from_user.id)
    if not user:
        return await callback.answer("Пользователь не найден", show_alert=True)

    # ИЩЕМ ИСТОРИЮ ПО ИМЕНИ И ТИПУ
    history_sets = await get_exercise_history(session, user.id, ex.name, ex.kind)
    if not history_sets:
        return await callback.answer("Нет данных для графика", show_alert=True)

    # === НОВЫЙ БЛОК: СТАТИСТИКА ПО ТРЕНИРОВКАМ ===
    from collections import defaultdict

    # Словарь: { "Название тренировки": {ID сессий} }
    workout_stats = defaultdict(set)
    for s in history_sets:
        if s.session and s.session.workout_type:
            workout_stats[s.session.workout_type.name].add(s.session.id)

    stats_lines = []
    for wt_name, session_ids in workout_stats.items():
        count = len(session_ids)
        # Склоняем слово "раз"
        if count % 10 == 1 and count % 100 != 11:
            word = "раз"
        elif count % 10 in [2, 3, 4] and count % 100 not in [12, 13, 14]:
            word = "раза"
        else:
            word = "раз"

        # Используем \n для переноса строки перед каждым пунктом
        stats_lines.append(f"• «{wt_name}» — {count} {word}")

    # Собираем текст: заголовок + список с новой строки
    info_text = "🔄 <b>Выполнялось:</b>\n" + "\n".join(stats_lines)
    # =================================================

    # --- ЛОГИКА ДЛЯ СИЛОВЫХ ---
    if ex.kind == "strength":
        prs = calculate_personal_records(history_sets)

        if prs['max_weight_str']:
            weight_display = prs['max_weight_str'] if re.search(
                r'[а-яА-Яa-zA-Z]',
                prs['max_weight_str']) else f"{prs['max_weight_str']} кг"
        else:
            weight_display = "Свой вес"

        best_set_text = "—"
        volume_unit = "кг"
        if prs['best_set']:
            best_set_text = f"{prs['best_set'].reps} × {prs['best_set'].weight_kg}"
            if re.search(r'[а-яА-Яa-zA-Z]', prs['best_set'].weight_kg):
                volume_unit = re.sub(r'[\d.,]', '',
                                     prs['best_set'].weight_kg).strip()

        text = (
            f"📈 <b>Прогресс: {ex.name}</b>\n"
            f"{info_text}\n\n"  # <--- ВСТАВИЛИ ИНФУ О ТРЕНИРОВКАХ
            f"🏆 <b>Личные рекорды:</b>\n"
            f"⚖️ Максимальный вес: <b>{weight_display}</b>\n"
            f"💪 Лучший подход по тоннажу: <b>{best_set_text}</b>\n"
            f"📊 Тоннаж: <b>{prs['max_volume']:g} {volume_unit}</b>\n\n"
            f"📉 График: максимальный вес за каждый день."
        )

        # Данные для графика (группировка по дням)
        daily_max = defaultdict(float)
        for s in history_sets:
            if s.session and s.session.started_at and s.weight_kg:
                match = re.search(r'\d+(?:[.,]\d+)?', s.weight_kg.replace(',', '.'))
                if match:
                    w = float(match.group())
                    from app.utils import to_msk
                    day = to_msk(s.session.started_at).date()
                    if w > daily_max[day]:
                        daily_max[day] = w

        if not daily_max:
            await callback.message.answer(text,
                                          reply_markup=exercise_progress_kb(
                                              session_id, page))
            await callback.answer()
            return

        sorted_days = sorted(daily_max.keys())
        dates = [datetime.combine(d, time(12, 0)) for d in sorted_days]
        values = [daily_max[d] for d in sorted_days]
        chart_title = f"Прогресс: {ex.name}"
        y_label = "Вес (кг)"

    # --- ЛОГИКА ДЛЯ КАРДИО ---
    else:
        max_duration = 0
        total_duration = 0
        for s in history_sets:
            if s.duration_seconds:
                total_duration += s.duration_seconds
                if s.duration_seconds > max_duration:
                    max_duration = s.duration_seconds

        def fmt_time(sec):
            if not sec: return "—"
            m, s = divmod(sec, 60)
            return f"{m} мин {s} сек" if m > 0 else f"{s} сек"

        text = (
            f"📈 <b>Прогресс: {ex.name}</b>\n"
            f"{info_text}\n\n"
            f"🏆 <b>Личные рекорды:</b>\n"
            f"⏱ Максимальное время за раз: <b>{fmt_time(max_duration)}</b>\n"
            f"⏳ Общее время за всё время: <b>{fmt_time(total_duration)}</b>\n\n"
            f"📉 График: максимальное время за каждый день."
        )

        # ВОТ ЭТУ СТРОКУ НУЖНО ДОБАВИТЬ:
        daily_max = defaultdict(int)

        for s in history_sets:
            if s.session and s.session.started_at and s.duration_seconds:
                # ИСПРАВЛЕНИЕ: Конвертируем в МСК
                from app.utils import to_msk
                day = to_msk(s.session.started_at).date()
                if s.duration_seconds > daily_max[day]:
                    daily_max[day] = s.duration_seconds

        if not daily_max:
            await callback.message.answer(text,
                                          reply_markup=exercise_progress_kb(
                                              session_id, page))
            await callback.answer()
            return

        sorted_days = sorted(daily_max.keys())
        dates = [datetime.combine(d, time(12, 0)) for d in sorted_days]
        values = [daily_max[d] / 60 for d in sorted_days]  # В минутах
        chart_title = f"Прогресс: {ex.name}"
        y_label = "Время (мин)"

    # --- ГЕНЕРАЦИЯ И ОТПРАВКА ---
    chart_buf = await asyncio.to_thread(generate_progress_chart, dates, values,
                                        chart_title, y_label)
    photo = BufferedInputFile(chart_buf.read(),
                              filename=f"progress_{ex_id}.png")

    await callback.message.answer_photo(
        photo=photo,
        caption=text,
        reply_markup=exercise_progress_kb(session_id, page)
    )
    await callback.answer()
