"""Экспорт расписания в календарь (п. 32)."""

import logging
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.render.directory import subject_list
from bot.render.ics import KIND_BITS
from bot.services.calendar import (
    ALARM_STEPS,
    CalendarFeeds,
    feed_url,
    get_prefs,
    get_token,
    subscribe_links,
    update_prefs,
)
from bot.services.schedule import ScheduleService
from bot.services.users import get_group, get_user

router = Router(name="calendar")
log = logging.getLogger(__name__)

_TRANSLIT = str.maketrans(
    "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ",
    "ABVGDEEZZIJKLMNOPRSTUFHCCSS_Y_EUA",
)


async def _menu(tg_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
    user = await get_user(tg_id)
    if not user or not user.group_id:
        return None
    group = await get_group(user.group_id)
    rows: list[list[InlineKeyboardButton]] = []
    text = f"<b>📅 Экспорт в календарь</b>\nГруппа: <b>{escape(group.name)}</b>\n\n"
    url = feed_url(await get_token(tg_id))
    if url:
        links = subscribe_links(url, f"Расписание {group.name}")
        text += (
            "<b>Подписка</b> — календарь сам подтягивает изменения расписания (обычно раз в несколько часов).\n"
            f"Ссылка для подписки:\n<code>{escape(url)}</code>\n\n"
            "Ссылка личная: не публикуйте её. Если она утекла — сбросьте.\n\n"
        )
        rows += [
            [
                InlineKeyboardButton(text="Google Календарь", url=links["google"]),
                InlineKeyboardButton(text="Outlook", url=links["outlook"]),
            ],
            [InlineKeyboardButton(text="Яндекс Календарь — как добавить", callback_data="cal:yandex")],
            [InlineKeyboardButton(text="🔄 Сбросить ссылку", callback_data="cal:reset")],
        ]
    text += "<b>Файл .ics</b> — разовый импорт расписания на весь семестр в любой календарь."
    rows.append([InlineKeyboardButton(text="📥 Скачать файл .ics", callback_data="cal:file")])
    rows.append([InlineKeyboardButton(text="🧩 Конструктор календаря", callback_data="cal:cfg")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "cal:menu")
async def menu(cb: CallbackQuery) -> None:
    res = await _menu(cb.from_user.id)
    await cb.answer()
    if res is None:
        await cb.message.answer("Сначала выберите группу: /change")
        return
    await cb.message.answer(res[0], reply_markup=res[1], disable_web_page_preview=True)


@router.callback_query(F.data == "cal:reset")
async def reset(cb: CallbackQuery) -> None:
    await get_token(cb.from_user.id, reset=True)
    res = await _menu(cb.from_user.id)
    await cb.answer("Ссылка сброшена. Старые подписки перестанут обновляться.", show_alert=True)
    if res:
        try:
            await cb.message.edit_text(res[0], reply_markup=res[1], disable_web_page_preview=True)
        except TelegramBadRequest:
            pass


@router.callback_query(F.data == "cal:yandex")
async def yandex(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.answer(
        "<b>Яндекс Календарь</b>\n\n"
        "1. Откройте calendar.yandex.ru в браузере.\n"
        "2. Слева «Новый календарь» → «Подписаться на календарь».\n"
        "3. Вставьте ссылку для подписки из сообщения выше и сохраните."
    )


@router.callback_query(F.data == "cal:file")
async def file(cb: CallbackQuery, calendar_feeds: CalendarFeeds) -> None:
    user = await get_user(cb.from_user.id)
    if not user or not user.group_id:
        await cb.answer("Сначала выберите группу: /change", show_alert=True)
        return
    await cb.answer("Готовлю файл…")
    group = await get_group(user.group_id)
    try:
        data = await calendar_feeds.for_group(group.id, await get_prefs(cb.from_user.id))
    except Exception:
        log.exception("файл календаря")
        await cb.message.answer("Сайт расписания сейчас недоступен, попробуйте чуть позже.")
        return
    name = "schedule-" + group.name.upper().translate(_TRANSLIT) + ".ics"
    await cb.message.answer_document(
        BufferedInputFile(data, filename=name),
        caption="Откройте файл — телефон предложит добавить занятия в календарь.\n\n"
        "Совет: импортируйте в <b>отдельный календарь</b> — тогда убрать расписание можно одним "
        "удалением этого календаря. Это разовый импорт: изменения расписания в него не попадут.",
    )


# --- конструктор календаря ---

KIND_TITLES = {"Лекция": "Лекции", "Практика": "Практики", "Лабораторная": "Лабораторные"}


def _cfg_kb(prefs, subjects: list[str]) -> InlineKeyboardMarkup:
    kinds = [
        InlineKeyboardButton(
            text=f"{'✅' if prefs.kinds_mask & bit else '⬜'} {KIND_TITLES[k]}", callback_data=f"cal:k:{bit}"
        )
        for k, bit in KIND_BITS.items()
    ]
    alarm = f"за {prefs.alarm_minutes} мин" if prefs.alarm_minutes else "выкл"
    rows = [kinds, [InlineKeyboardButton(text=f"🔔 Напоминание в календаре: {alarm}", callback_data="cal:a")]]
    for i, name in enumerate(subjects):
        mark = "⬜" if name in prefs.hidden_subjects else "✅"
        rows.append([InlineKeyboardButton(text=f"{mark} {name}"[:60], callback_data=f"cal:h:{i}")])
    rows.append([InlineKeyboardButton(text="⬅️ К экспорту", callback_data="cal:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


CFG_TEXT = (
    "<b>🧩 Конструктор календаря</b>\n\n"
    "Выберите, какие занятия попадут в календарь, и нужно ли напоминание. "
    "Настройки действуют и на файл .ics, и на подписку (она обновится сама)."
)


async def _subjects(schedule: ScheduleService, tg_id: int) -> list[str]:
    user = await get_user(tg_id)
    if not user or not user.group_id:
        return []
    return subject_list(await schedule.semester(user.group_id))


@router.callback_query(
    F.data.startswith("cal:cfg") | F.data.startswith("cal:k:") | F.data.startswith("cal:h:") | (F.data == "cal:a")
)
async def builder(cb: CallbackQuery, schedule: ScheduleService) -> None:
    tg = cb.from_user.id
    try:
        subjects = await _subjects(schedule, tg)
    except Exception:
        log.exception("конструктор календаря")
        await cb.answer("Сайт расписания сейчас недоступен", show_alert=True)
        return
    prefs = await get_prefs(tg)
    parts = cb.data.split(":")
    if parts[1] == "k":
        prefs = await update_prefs(tg, kinds_mask=prefs.kinds_mask ^ int(parts[2]))
    elif parts[1] == "a":
        cur = prefs.alarm_minutes if prefs.alarm_minutes in ALARM_STEPS else 0
        prefs = await update_prefs(tg, alarm_minutes=ALARM_STEPS[(ALARM_STEPS.index(cur) + 1) % len(ALARM_STEPS)])
    elif parts[1] == "h" and int(parts[2]) < len(subjects):
        name = subjects[int(parts[2])]
        hidden = set(prefs.hidden_subjects) ^ {name}
        prefs = await update_prefs(tg, hidden_subjects=sorted(hidden))
    await cb.answer()
    kb = _cfg_kb(prefs, subjects)
    if parts[1] == "cfg":
        await cb.message.answer(CFG_TEXT, reply_markup=kb)
    else:
        try:
            await cb.message.edit_reply_markup(reply_markup=kb)
        except TelegramBadRequest:
            pass
