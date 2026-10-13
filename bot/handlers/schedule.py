"""Просмотр расписания группы (п. 1–5, 7)."""
import logging
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.handlers.start import ask_group
from bot.keyboards.main import Btn, day_nav, week_nav
from bot.render.text import render_day, render_period, render_week
from bot.services.schedule import ScheduleService, monday_of, today
from bot.services.users import get_group, get_user

router = Router(name="schedule")
log = logging.getLogger(__name__)

UNAVAILABLE = "Сайт расписания сейчас недоступен, попробуйте чуть позже."


async def _group(tg_id: int):
    user = await get_user(tg_id)
    if not user or not user.group_id:
        return None
    return await get_group(user.group_id)


async def _day_text(schedule: ScheduleService, group, day: date) -> str:
    week = await schedule.week(group.id, day)
    return render_day(group.name, week, day)


async def _send_day(message: Message, state: FSMContext, schedule: ScheduleService, day: date) -> None:
    group = await _group(message.from_user.id)
    if group is None:
        await ask_group(message, state)
        return
    try:
        text = await _day_text(schedule, group, day)
    except Exception:
        log.exception("расписание дня")
        await message.answer(UNAVAILABLE)
        return
    await message.answer(text, reply_markup=day_nav(day))


@router.message(F.text == Btn.TODAY)
async def today_msg(message: Message, state: FSMContext, schedule: ScheduleService) -> None:
    await _send_day(message, state, schedule, today())


@router.message(F.text == Btn.TOMORROW)
async def tomorrow_msg(message: Message, state: FSMContext, schedule: ScheduleService) -> None:
    await _send_day(message, state, schedule, today() + timedelta(days=1))


async def _send_week(message: Message, state: FSMContext, schedule: ScheduleService, monday: date) -> None:
    group = await _group(message.from_user.id)
    if group is None:
        await ask_group(message, state)
        return
    try:
        week = await schedule.week(group.id, monday)
    except Exception:
        log.exception("расписание недели")
        await message.answer(UNAVAILABLE)
        return
    await message.answer(render_week(group.name, week), reply_markup=week_nav(monday))


@router.message(F.text == Btn.WEEK)
async def week_msg(message: Message, state: FSMContext, schedule: ScheduleService) -> None:
    await _send_week(message, state, schedule, monday_of(today()))


@router.message(F.text == Btn.NEXT_WEEK)
async def next_week_msg(message: Message, state: FSMContext, schedule: ScheduleService) -> None:
    await _send_week(message, state, schedule, monday_of(today()) + timedelta(days=7))


@router.message(F.text == Btn.MONTH)
async def month_msg(message: Message, state: FSMContext, schedule: ScheduleService) -> None:
    group = await _group(message.from_user.id)
    if group is None:
        await ask_group(message, state)
        return
    start = today()
    end = start + timedelta(days=30)
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        lessons = await schedule.lessons_between(group.id, start, end)
    except Exception:
        log.exception("расписание на месяц")
        await message.answer(UNAVAILABLE)
        return
    for part in render_period(group.name, lessons, start, end):
        await message.answer(part)


# --- листание (редактируем то же сообщение) ---


async def _edit(cb: CallbackQuery, text: str, markup) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


@router.callback_query(F.data.startswith("d:"))
async def day_cb(cb: CallbackQuery, state: FSMContext, schedule: ScheduleService) -> None:
    group = await _group(cb.from_user.id)
    if group is None:
        await cb.answer()
        await ask_group(cb.message, state)
        return
    day = date.fromisoformat(cb.data[2:])
    try:
        text = await _day_text(schedule, group, day)
    except Exception:
        log.exception("листание дня")
        await cb.answer(UNAVAILABLE, show_alert=True)
        return
    await cb.answer()
    await _edit(cb, text, day_nav(day))


@router.callback_query(F.data.startswith("w:"))
async def week_cb(cb: CallbackQuery, state: FSMContext, schedule: ScheduleService) -> None:
    group = await _group(cb.from_user.id)
    if group is None:
        await cb.answer()
        await ask_group(cb.message, state)
        return
    monday = date.fromisoformat(cb.data[2:])
    try:
        week = await schedule.week(group.id, monday)
    except Exception:
        log.exception("листание недели")
        await cb.answer(UNAVAILABLE, show_alert=True)
        return
    await cb.answer()
    await _edit(cb, render_week(group.name, week), week_nav(monday))
