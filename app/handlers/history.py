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
    page = int(parts[2])  # Достаем страницу, с которой пришли

    # Загружаем сессию со всеми связями
    ws = await get_session_details(session, session_id)
    if not ws:
        return await callback.answer("Тренировка не найдена", show_alert=True)

    # Рендерим текст
    text = render_history_details(ws)

    try:
        await callback.message.edit_text(
            text,
            reply_markup=history_details_kb(page)
        )
    except Exception as e:
        # На случай, если текст не изменился
        pass

    await callback.answer()
