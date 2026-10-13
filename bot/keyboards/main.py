from datetime import date, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from bot.db.models import User
from bot.legal import DOCUMENTS


class Btn:
    TODAY = "📅 Сегодня"
    TOMORROW = "➡️ Завтра"
    WEEK = "🗓 Эта неделя"
    NEXT_WEEK = "⏭ След. неделя"
    MONTH = "📆 На месяц"
    SETTINGS = "⚙️ Настройки"
    DOCS = "📄 Документы"


def main_menu() -> ReplyKeyboardMarkup:
    b = KeyboardButton
    return ReplyKeyboardMarkup(
        keyboard=[
            [b(text=Btn.TODAY), b(text=Btn.TOMORROW)],
            [b(text=Btn.WEEK), b(text=Btn.NEXT_WEEK)],
            [b(text=Btn.MONTH)],
            [b(text=Btn.SETTINGS), b(text=Btn.DOCS)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие…",
    )


def consent_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📄 {d.title}", callback_data=f"legal:show:{d.code}")] for d in DOCUMENTS]
    rows.append([InlineKeyboardButton(text="✅ Принимаю все документы", callback_data="legal:accept")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def docs_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"📄 {d.title}", callback_data=f"legal:show:{d.code}")] for d in DOCUMENTS
        ]
    )


def day_nav(day: date) -> InlineKeyboardMarkup:
    def cb(d: date) -> str:
        return f"d:{d.isoformat()}"

    prev, nxt = day - timedelta(days=1), day + timedelta(days=1)
    if prev.weekday() == 6:
        prev -= timedelta(days=1)
    if nxt.weekday() == 6:
        nxt += timedelta(days=1)
    monday = day - timedelta(days=day.weekday())
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"⬅️ {prev:%d.%m}", callback_data=cb(prev)),
                InlineKeyboardButton(text=f"{nxt:%d.%m} ➡️", callback_data=cb(nxt)),
            ],
            [
                InlineKeyboardButton(
                    text=f"⏪ {day - timedelta(days=7):%d.%m}", callback_data=cb(day - timedelta(days=7))
                ),
                InlineKeyboardButton(
                    text=f"{day + timedelta(days=7):%d.%m} ⏩", callback_data=cb(day + timedelta(days=7))
                ),
            ],
            [InlineKeyboardButton(text="🗓 Вся неделя", callback_data=f"w:{monday.isoformat()}")],
        ]
    )


def week_nav(monday: date) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Неделя назад", callback_data=f"w:{(monday - timedelta(days=7)).isoformat()}"
                ),
                InlineKeyboardButton(
                    text="Неделя вперёд ➡️", callback_data=f"w:{(monday + timedelta(days=7)).isoformat()}"
                ),
            ]
        ]
    )


def settings_kb(user: User) -> InlineKeyboardMarkup:
    def toggle(flag: bool, title: str, field: str) -> list[InlineKeyboardButton]:
        return [InlineKeyboardButton(text=f"{'✅' if flag else '❌'} {title}", callback_data=f"set:{field}")]

    return InlineKeyboardMarkup(
        inline_keyboard=[
            toggle(user.notify_tomorrow, "Расписание на завтра (20:00)", "notify_tomorrow"),
            toggle(user.notify_week, "Расписание на неделю (вс 18:00)", "notify_week"),
            toggle(user.notify_changes, "Изменения в расписании", "notify_changes"),
            [InlineKeyboardButton(text="🔁 Сменить группу", callback_data="set:group")],
        ]
    )


def groups_choice(groups) -> InlineKeyboardMarkup:
    rows, row = [], []
    for g in groups:
        row.append(InlineKeyboardButton(text=g.name, callback_data=f"grp:{g.id}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delete_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Да, удалить всё", callback_data="del:yes")],
            [InlineKeyboardButton(text="Отмена", callback_data="del:no")],
        ]
    )
