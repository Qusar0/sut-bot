"""Просмотр расписания группы (п. 1–7)."""

import asyncio
import logging
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot import metrics
from bot.handlers.start import ask_group
from bot.keyboards.main import Btn, day_nav, month_calendar, week_nav
from bot.render.image import lesson_counters, render_day_image
from bot.render.text import render_day, render_period, render_week, week_label
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


async def _send_day(
    message: Message, state: FSMContext, schedule: ScheduleService, day: date, tg_id: int | None = None
) -> None:
    group = await _group(tg_id or message.from_user.id)
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
        weeks = await schedule.weeks_between(group.id, start, end)
    except Exception:
        log.exception("расписание на месяц")
        await message.answer(UNAVAILABLE)
        return
    parts = render_period(group.name, weeks, start, end)
    lesson_days = {l.day for w in weeks for l in w.lessons if start <= l.day <= end}
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        await message.answer(part, reply_markup=month_calendar(start, end, lesson_days) if last else None)


@router.callback_query(F.data.startswith("dn:"))
async def day_new_cb(cb: CallbackQuery, state: FSMContext, schedule: ScheduleService) -> None:
    """Нажатие на день в календаре месяца — новым сообщением, чтобы календарь остался."""
    await cb.answer()
    await _send_day(cb.message, state, schedule, date.fromisoformat(cb.data[3:]), tg_id=cb.from_user.id)


_images: dict[tuple, bytes] = {}  # (группа, день, состав пар) -> PNG


@router.callback_query(F.data.startswith("img:"))
async def day_image_cb(cb: CallbackQuery, state: FSMContext, schedule: ScheduleService) -> None:
    """Расписание дня картинкой (п. 6)."""
    group = await _group(cb.from_user.id)
    if group is None:
        await cb.answer()
        await ask_group(cb.message, state)
        return
    day = date.fromisoformat(cb.data[4:])
    await cb.answer("Рисую…")
    try:
        week = await schedule.week(group.id, day)
        lessons = week.by_day(day)
        key = (group.id, day, tuple(l.key() for l in lessons))
        png = _images.get(key)
        if png is None:
            semester = await schedule.semester(group.id)
            counters = lesson_counters([l for w in semester for l in w.lessons])
            with metrics.timer("картинка: рисование"):
                png = await asyncio.to_thread(render_day_image, group.name, day, lessons, week_label(week), counters)
            if len(_images) > 500:
                _images.clear()
            _images[key] = png
    except Exception:
        log.exception("картинка расписания")
        await cb.message.answer(UNAVAILABLE)
        return
    await cb.message.answer_photo(BufferedInputFile(png, filename=f"{day.isoformat()}.png"), reply_markup=day_nav(day))


@router.callback_query(F.data == "noop")
async def noop_cb(cb: CallbackQuery) -> None:
    await cb.answer()


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
