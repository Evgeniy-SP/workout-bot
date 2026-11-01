"""Хэндлеры для таймеров отдыха."""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, \
    InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkoutSession
from app.db.session import async_session_maker
from app.keyboards.workout_kb import cancel_kb
from app.services.training_service import (
    ACTIVE_TIMERS, render_approach_screen, render_list,
)
from app.states import TrainingFSM

logger = logging.getLogger(__name__)
router = Router()


async def _run_rest_timer(bot, chat_id: int, session_id: int, seconds: int):
    """Фоновая задача таймера."""
    try:
        await asyncio.sleep(seconds)

        async with async_session_maker() as session:
            ws = await session.get(WorkoutSession, session_id)
            if not ws or ws.finished_at is not None:
                return

        timer_data = ACTIVE_TIMERS.pop(session_id, None)
        if not timer_data:
            return

        # Перерисовываем старый экран (убираем кнопку "Остановить")
        if timer_data.get("message_id"):
            async with async_session_maker() as session:
                try:
                    if timer_data["context"] == "ex":
                        result = await render_approach_screen(session,
                                                              session_id,
                                                              timer_data[
                                                                  "ex_id"])
                        if result:
                            text, kb = result
                            await bot.edit_message_text(
                                chat_id=timer_data["chat_id"],
                                message_id=timer_data["message_id"],
                                text=text,
                                reply_markup=kb
                            )
                    else:
                        ws = await session.get(WorkoutSession, session_id)
                        if ws:
                            text, kb = await render_list(session, session_id,
                                                         ws.user_id)
                            await bot.edit_message_text(
                                chat_id=timer_data["chat_id"],
                                message_id=timer_data["message_id"],
                                text=text,
                                reply_markup=kb
                            )
                except Exception as e:
                    logger.error(f"Ошибка при очистке кнопки таймера: {e}")

        # Отправляем уведомление
        msg = await bot.send_message(
            chat_id=chat_id,
            text=f"⏰ <b>Отдых окончен!</b> Пора делать следующий подход.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Понятно",
                                      callback_data="tr_timer_dismiss")]
            ])
        )

        await asyncio.sleep(15)
        try:
            await msg.delete()
        except Exception:
            pass
    except asyncio.CancelledError:
        # Если таймер отменили вручную, просто выходим
        pass
    finally:
        # ВАЖНО: удаляем из словаря ТОЛЬКО если там лежит именно наша задача
        if session_id in ACTIVE_TIMERS and ACTIVE_TIMERS[session_id][
            "task"] == asyncio.current_task():
            ACTIVE_TIMERS.pop(session_id, None)


@router.callback_query(F.data.startswith("tr_timer:"))
async def cb_start_timer(callback: CallbackQuery, session: AsyncSession):
    parts = callback.data.split(":")
    seconds = int(parts[1])
    session_id = int(parts[2])

    if session_id in ACTIVE_TIMERS:
        ACTIVE_TIMERS[session_id]["task"].cancel()

    task = asyncio.create_task(_run_rest_timer(
        callback.bot, callback.message.chat.id, session_id, seconds
    ))

    context = "ex" if len(parts) > 3 and parts[3] == "ex" else "list"
    ex_id = int(parts[4]) if context == "ex" else None

    ACTIVE_TIMERS[session_id] = {
        "task": task,
        "duration": seconds,
        "end_time": datetime.now(timezone.utc) + timedelta(seconds=seconds),
        "chat_id": callback.message.chat.id,
        "message_id": callback.message.message_id,
        "context": context,
        "ex_id": ex_id
    }

    await callback.answer(f"⏱ Таймер на {seconds} секунд запущен",
                          show_alert=True)

    try:
        if context == "ex":
            result = await render_approach_screen(session, session_id, ex_id)
            if result:
                text, kb = result
                await callback.message.edit_text(text, reply_markup=kb)
        else:
            ws = await session.get(WorkoutSession, session_id)
            if ws:
                text, kb = await render_list(session, session_id, ws.user_id)
                await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass


@router.callback_query(F.data.startswith("tr_timer_custom:"))
async def cb_timer_custom_start(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    session_id = int(parts[1])

    if parts[2] == "list":
        await state.update_data(session_id=session_id,
                                return_to_session=session_id,
                                return_to="tr_list")
    else:
        ex_id = int(parts[3])
        await state.update_data(session_id=session_id, ex_id=ex_id,
                                return_to="tr_ex_card")

    await state.set_state(TrainingFSM.entering_rest_time)
    await callback.message.edit_text(
        "⏱ <b>Своё время отдыха</b>\n\nВведи количество секунд (например, 45):",
        reply_markup=cancel_kb()
    )
    await callback.answer()


@router.message(TrainingFSM.entering_rest_time)
async def fsm_timer_custom_save(message: Message, state: FSMContext,
                                session: AsyncSession):
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        return await message.answer(
            "Нужно целое число больше 0. Попробуй ещё:")

    seconds = int(text)
    data = await state.get_data()
    session_id = data["session_id"]
    return_to = data.get("return_to")
    ex_id = data.get("ex_id")

    if session_id in ACTIVE_TIMERS:
        ACTIVE_TIMERS[session_id]["task"].cancel()

    task = asyncio.create_task(_run_rest_timer(
        message.bot, message.chat.id, session_id, seconds
    ))
    ACTIVE_TIMERS[session_id] = {
        "task": task,
        "duration": seconds,
        "end_time": datetime.now(timezone.utc) + timedelta(seconds=seconds),
        "chat_id": message.chat.id,
        "message_id": None,
        "context": "ex" if return_to == "tr_ex_card" and ex_id else "list",
        "ex_id": ex_id
    }

    await state.clear()

    if return_to == "tr_ex_card" and ex_id:
        result = await render_approach_screen(session, session_id, ex_id)
        if result:
            text_screen, kb = result
            sent_msg = await message.answer(
                f"⏱ Таймер на {seconds} сек запущен.\n\n" + text_screen,
                reply_markup=kb)
            ACTIVE_TIMERS[session_id]["message_id"] = sent_msg.message_id
    else:
        ws = await session.get(WorkoutSession, session_id)
        text_screen, kb = await render_list(session, session_id, ws.user_id)
        sent_msg = await message.answer(
            f"⏱ Таймер на {seconds} сек запущен.\n\n" + text_screen,
            reply_markup=kb)
        ACTIVE_TIMERS[session_id]["message_id"] = sent_msg.message_id


@router.callback_query(F.data == "tr_timer_dismiss")
async def cb_timer_dismiss(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("tr_timer_stop:"))
async def cb_timer_stop(callback: CallbackQuery, session: AsyncSession):
    parts = callback.data.split(":")
    session_id = int(parts[1])

    if session_id in ACTIVE_TIMERS:
        ACTIVE_TIMERS[session_id]["task"].cancel()
        ACTIVE_TIMERS.pop(session_id, None)

    try:
        if len(parts) > 3 and parts[2] == "ex":
            ex_id = int(parts[3])
            result = await render_approach_screen(session, session_id, ex_id)
            if result:
                text, kb = result
                await callback.message.edit_text(
                    "⏹ Таймер остановлен.\n\n" + text, reply_markup=kb)
        else:
            ws = await session.get(WorkoutSession, session_id)
            if ws:
                text, kb = await render_list(session, session_id, ws.user_id)
                await callback.message.edit_text(
                    "⏹ Таймер остановлен.\n\n" + text, reply_markup=kb)
    except Exception:
        pass

    await callback.answer("Таймер остановлен")
