"""Преподаватели (п. 11, 12), аудитории (п. 16, 17), предметы (п. 20–22, 24)."""

import logging
from collections import Counter
from datetime import date, timedelta
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.keyboards.main import KIND_BITS, Btn, choice_list, entity_day_nav, entity_week_nav, subject_kb
from bot.render.directory import (
    KINDS,
    PHOTO_CAPTION_LIMIT,
    base_subject,
    render_profile,
    render_slots_day,
    render_slots_week,
    render_subject,
    render_subjects,
    room_tail,
    subject_list,
    subject_stats,
    teacher_tail,
)
from bot.services.directory import Directory, room_label
from bot.services.schedule import ScheduleService, monday_of, today
from bot.services.staff import StaffService
from bot.services.users import get_group, get_user

router = Router(name="directory")
log = logging.getLogger(__name__)

UNAVAILABLE = "Сайт расписания сейчас недоступен, попробуйте чуть позже."
PARTIAL_NOTE = (
    "\n\n<i>ℹ️ Расписание преподавателей и аудиторий собирается из расписаний всех групп "
    "и полное только на текущую и следующую неделю.</i>"
)


class Search(StatesGroup):
    teacher = State()
    room = State()


async def _edit(cb: CallbackQuery, text: str, markup) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


async def _show(cb: CallbackQuery, text: str, markup) -> None:
    """Из списка выбора — новым сообщением (список остаётся), при листании — редактируем."""
    src = cb.message.text or ""
    if src.startswith(("Нашлось", "📋")):
        await cb.message.answer(text, reply_markup=markup)
    else:
        await _edit(cb, text, markup)


def _note(monday: date) -> str:
    cur = monday_of(today())
    return "" if monday in (cur, cur + timedelta(days=7)) else PARTIAL_NOTE


def _workday(d: date) -> date:
    return d + timedelta(days=1) if d.weekday() == 6 else d


async def _user_group(tg_id: int):
    user = await get_user(tg_id)
    return await get_group(user.group_id) if user and user.group_id else None


# ---------------- преподаватели ----------------


@router.message(F.text == Btn.TEACHERS)
async def teachers_menu(message: Message, state: FSMContext) -> None:
    await state.set_state(Search.teacher)
    await message.answer(
        "<b>👩‍🏫 Преподаватели</b>\n\nНапишите фамилию преподавателя (можно с инициалами), "
        "например <code>Воронова</code> или <code>Кокорин М</code>.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="📋 Мои преподаватели", callback_data="myt")]]
        ),
    )


async def _send_teacher_results(message: Message, directory: Directory, query: str) -> bool:
    found = directory.search_teachers(query)
    if not found:
        return False
    if len(found) == 1:
        await _send_teacher_day(message, directory, found[0].id, _workday(today()))
        return True
    await message.answer(
        "Нашлось несколько преподавателей:",
        reply_markup=choice_list(
            [(t.full_name, f"t:{t.id}:d:{_workday(today()).isoformat()}") for t in found], per_row=1
        ),
    )
    return True


@router.message(StateFilter(Search.teacher), F.text, ~F.text.in_(set(vars(Btn).values())))
async def teacher_query(message: Message, state: FSMContext, directory: Directory) -> None:
    if not await _send_teacher_results(message, directory, message.text):
        await message.answer("Не нашёл такого преподавателя. Попробуйте только фамилию.")


async def _teacher_day_text(directory: Directory, tid: int, day: date) -> str:
    t = directory.teacher(tid)
    slots = await directory.teacher_slots(tid, day, day)
    return render_slots_day(f"👩‍🏫 {t.full_name}", slots, day, teacher_tail) + _note(monday_of(day))


async def _send_teacher_day(message: Message, directory: Directory, tid: int, day: date) -> None:
    await message.answer(await _teacher_day_text(directory, tid, day), reply_markup=entity_day_nav("t", tid, day))


@router.callback_query(F.data.startswith("t:"))
async def teacher_cb(cb: CallbackQuery, directory: Directory) -> None:
    _, tid, mode, iso = cb.data.split(":")
    tid, d = int(tid), date.fromisoformat(iso)
    if directory.teacher(tid) is None:
        await cb.answer("Преподаватель не найден", show_alert=True)
        return
    await cb.answer()
    if mode == "d":
        text, kb = await _teacher_day_text(directory, tid, d), entity_day_nav("t", tid, d)
    else:
        t = directory.teacher(tid)
        slots = await directory.teacher_slots(tid, d, d + timedelta(days=5))
        text = render_slots_week(f"👩‍🏫 {t.full_name}", slots, d, teacher_tail) + _note(d)
        kb = entity_week_nav("t", tid, d)
    await _show(cb, text, kb)


@router.callback_query(F.data == "myt")
async def my_teachers(cb: CallbackQuery, schedule: ScheduleService, directory: Directory) -> None:
    group = await _user_group(cb.from_user.id)
    if group is None:
        await cb.answer("Сначала выберите группу: /change", show_alert=True)
        return
    await cb.answer()
    try:
        weeks = await schedule.semester(group.id)
    except Exception:
        log.exception("мои преподаватели")
        await cb.message.answer(UNAVAILABLE)
        return
    subjects: dict[str, set[str]] = {}
    for w in weeks:
        for l in w.lessons:
            for t in l.teachers:
                subjects.setdefault(t, set()).add(l.subject.split(" (")[0])
    items = []
    for full in sorted(subjects):
        t = directory.teacher_by_name(full)
        if t is None:
            continue
        label = f"{t.short_name} · {', '.join(sorted(subjects[full]))}"
        items.append((label[:60], f"t:{t.id}:d:{_workday(today()).isoformat()}"))
    if not items:
        await cb.message.answer("Пока не удалось собрать список, попробуйте через пару минут.")
        return
    await cb.message.answer(
        f"📋 <b>Преподаватели группы {escape(group.name)}</b>\n<i>текущий семестр</i>",
        reply_markup=choice_list(items),
    )


@router.callback_query(F.data.startswith("tp:"))
async def teacher_profile(
    cb: CallbackQuery, directory: Directory, staff: StaffService, schedule: ScheduleService
) -> None:
    t = directory.teacher(int(cb.data[3:]))
    if t is None:
        await cb.answer("Преподаватель не найден", show_alert=True)
        return
    await cb.answer()
    prof = await staff.profile(t.full_name)
    if prof is None:
        text = f"<b>👤 {escape(t.full_name)}</b>\n\nПрофиля на сайте sut.ru не нашлось."
        if not await staff.count():
            text += "\n<i>Список преподавателей ещё собирается, попробуйте позже.</i>"
        await cb.message.answer(text)
        return
    subjects: list[str] = []
    group = await _user_group(cb.from_user.id)
    if group is not None:
        week = await schedule.week(group.id, today())
        subjects = sorted({base_subject(l.subject) for l in week.lessons if t.full_name in l.teachers})
    text = render_profile(prof, subjects)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌐 Страница на sut.ru", url=prof.url)]])
    if prof.photo and len(text) <= PHOTO_CAPTION_LIMIT:
        try:
            await cb.message.answer_photo(prof.photo, caption=text, reply_markup=kb)
            return
        except TelegramBadRequest:
            pass  # фото недоступно — отправим текстом
    await cb.message.answer(text, reply_markup=kb, disable_web_page_preview=True)


# ---------------- аудитории ----------------


@router.message(F.text == Btn.ROOMS)
async def rooms_menu(message: Message, state: FSMContext) -> None:
    await state.set_state(Search.room)
    await message.answer(
        "<b>🚪 Аудитории</b>\n\nНапишите номер аудитории, например <code>303</code>, <code>501/2</code> или "
        "<code>Динамит</code>.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="📋 Аудитории моей группы", callback_data="myr")]]
        ),
    )


async def _send_room_results(message: Message, directory: Directory, query: str) -> bool:
    found = directory.search_rooms(query)
    if not found:
        return False
    day = _workday(today())
    if len(found) == 1:
        r = found[0]
        await message.answer(await _room_day_text(directory, r.id, day), reply_markup=entity_day_nav("r", r.id, day))
        return True
    await message.answer(
        "Нашлось несколько аудиторий:",
        reply_markup=choice_list(
            [(room_label(r.room, r.building), f"r:{r.id}:d:{day.isoformat()}") for r in found], per_row=3
        ),
    )
    return True


@router.message(StateFilter(Search.room), F.text, ~F.text.in_(set(vars(Btn).values())))
async def room_query(message: Message, directory: Directory) -> None:
    if not await _send_room_results(message, directory, message.text):
        await message.answer("Не нашёл такую аудиторию. Попробуйте только номер, например <code>303</code>.")


async def _room_day_text(directory: Directory, rid: int, day: date) -> str:
    r = directory.room(rid)
    slots = await directory.room_slots(rid, day, day)
    return render_slots_day(f"🚪 Аудитория {room_label(r.room, r.building)}", slots, day, room_tail) + _note(
        monday_of(day)
    )


@router.callback_query(F.data.startswith("r:"))
async def room_cb(cb: CallbackQuery, directory: Directory) -> None:
    _, rid, mode, iso = cb.data.split(":")
    rid, d = int(rid), date.fromisoformat(iso)
    r = directory.room(rid)
    if r is None:
        await cb.answer("Аудитория не найдена", show_alert=True)
        return
    await cb.answer()
    if mode == "d":
        text, kb = await _room_day_text(directory, rid, d), entity_day_nav("r", rid, d)
    else:
        slots = await directory.room_slots(rid, d, d + timedelta(days=5))
        text = render_slots_week(f"🚪 Аудитория {room_label(r.room, r.building)}", slots, d, room_tail) + _note(d)
        kb = entity_week_nav("r", rid, d)
    await _show(cb, text, kb)


@router.callback_query(F.data == "myr")
async def my_rooms(cb: CallbackQuery, schedule: ScheduleService, directory: Directory) -> None:
    group = await _user_group(cb.from_user.id)
    if group is None:
        await cb.answer("Сначала выберите группу: /change", show_alert=True)
        return
    await cb.answer()
    try:
        weeks = await schedule.semester(group.id)
    except Exception:
        log.exception("мои аудитории")
        await cb.message.answer(UNAVAILABLE)
        return
    usage = Counter((l.room, l.building) for w in weeks for l in w.lessons if l.room)
    day = _workday(today()).isoformat()
    items = []
    for (room, building), n in usage.most_common(30):
        if (r := directory.room_by_key(room, building)) is not None:
            items.append((f"{room_label(room, building)} · {n}", f"r:{r.id}:d:{day}"))
    if not items:
        await cb.message.answer("Пока не удалось собрать список, попробуйте через пару минут.")
        return
    await cb.message.answer(
        f"📋 <b>Аудитории группы {escape(group.name)}</b>\n<i>текущий семестр · число занятий</i>",
        reply_markup=choice_list(items, per_row=2),
    )


# ---------------- предметы ----------------


async def _semester(cb_or_msg, schedule: ScheduleService, tg_id: int):
    group = await _user_group(tg_id)
    if group is None:
        return None, None
    return group, await schedule.semester(group.id)


def _subjects_kb(weeks) -> InlineKeyboardMarkup:
    items = []
    for i, name in enumerate(subject_list(weeks)):
        st = subject_stats(weeks, name)
        items.append((f"{name} · {st.passed}/{len(st.lessons)}", f"subj:{i}:7"))
    return choice_list(items)


@router.message(F.text == Btn.SUBJECTS)
async def subjects_menu(message: Message, schedule: ScheduleService) -> None:
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        group, weeks = await _semester(message, schedule, message.from_user.id)
    except Exception:
        log.exception("предметы")
        await message.answer(UNAVAILABLE)
        return
    if group is None:
        await message.answer("Сначала выберите группу: /change")
        return
    await message.answer(render_subjects(group.name, weeks), reply_markup=_subjects_kb(weeks))


@router.callback_query(F.data.startswith("subj:"))
async def subject_cb(cb: CallbackQuery, schedule: ScheduleService) -> None:
    await cb.answer()
    try:
        group, weeks = await _semester(cb, schedule, cb.from_user.id)
    except Exception:
        log.exception("карточка предмета")
        await cb.answer(UNAVAILABLE, show_alert=True)
        return
    if group is None:
        return
    if cb.data == "subj:list":
        await _edit(cb, render_subjects(group.name, weeks), _subjects_kb(weeks))
        return
    _, idx, mask = cb.data.split(":")
    names = subject_list(weeks)
    idx, mask = int(idx), int(mask)
    if idx >= len(names):
        return
    stats = subject_stats(weeks, names[idx])
    present = [k for k in KINDS if k in stats.by_kind]
    kinds = {k for k in KINDS if mask & KIND_BITS[k]}
    text = render_subject(group.name, weeks, stats, kinds)
    await _edit(cb, text, subject_kb(idx, mask, present))


# ---------------- свободный текст ----------------


@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def free_text(message: Message, directory: Directory) -> None:
    """Текст вне меню: цифры — ищем аудиторию, иначе — преподавателя."""
    q = message.text.strip()
    if any(ch.isdigit() for ch in q):
        if await _send_room_results(message, directory, q):
            return
    elif await _send_teacher_results(message, directory, q):
        return
    await message.answer(
        "Не понял запрос 🤔\nПользуйтесь кнопками меню или напишите фамилию преподавателя / номер аудитории."
    )
