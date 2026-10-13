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
    TEACHERS = "👩‍🏫 Преподаватели"
    SUBJECTS = "📚 Предметы"
    ROOMS = "🚪 Аудитории"
    LK = "🏛 Личный кабинет"
    SETTINGS = "⚙️ Настройки"
    DOCS = "📄 Документы"


def main_menu() -> ReplyKeyboardMarkup:
    b = KeyboardButton
    return ReplyKeyboardMarkup(
        keyboard=[
            [b(text=Btn.TODAY), b(text=Btn.TOMORROW)],
            [b(text=Btn.WEEK), b(text=Btn.NEXT_WEEK)],
            [b(text=Btn.MONTH)],
            [b(text=Btn.TEACHERS), b(text=Btn.SUBJECTS), b(text=Btn.ROOMS)],
            [b(text=Btn.LK)],
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
            [
                InlineKeyboardButton(text="🗓 Вся неделя", callback_data=f"w:{monday.isoformat()}"),
                InlineKeyboardButton(text="🖼 Картинкой", callback_data=f"img:{day.isoformat()}"),
            ],
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
            [
                InlineKeyboardButton(
                    text=f"⏰ Перед парой: {f'за {user.remind_minutes} мин' if user.remind_minutes else 'выкл'}",
                    callback_data="set:remind_minutes",
                )
            ],
            toggle(user.morning_digest, "Утренняя сводка (7:30)", "morning_digest"),
            toggle(user.quiet_hours, "Тихие часы 23:00–7:00 (без звука)", "quiet_hours"),
            [InlineKeyboardButton(text="📅 Экспорт в календарь", callback_data="cal:menu")],
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


def month_calendar(start: date, end: date, lesson_days: set[date]) -> InlineKeyboardMarkup:
    """Календарь Пн–Сб: дни с парами кликабельны и открывают расписание дня."""
    noop = "noop"
    rows = [[InlineKeyboardButton(text=t, callback_data=noop) for t in ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб")]]
    monday = start - timedelta(days=start.weekday())
    while monday <= end:
        row = []
        for i in range(6):
            d = monday + timedelta(days=i)
            if not start <= d <= end:
                row.append(InlineKeyboardButton(text=" ", callback_data=noop))
            elif d in lesson_days:
                row.append(InlineKeyboardButton(text=str(d.day), callback_data=f"dn:{d.isoformat()}"))
            else:
                row.append(InlineKeyboardButton(text="·", callback_data=noop))
        rows.append(row)
        monday += timedelta(days=7)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _profile_row(prefix: str, eid: int) -> list[list[InlineKeyboardButton]]:
    return [[InlineKeyboardButton(text="👤 Профиль", callback_data=f"tp:{eid}")]] if prefix == "t" else []


def entity_day_nav(prefix: str, eid: int, day: date) -> InlineKeyboardMarkup:
    """Листание расписания преподавателя (prefix="t") или аудитории (prefix="r") по дням."""
    prev, nxt = day - timedelta(days=1), day + timedelta(days=1)
    if prev.weekday() == 6:
        prev -= timedelta(days=1)
    if nxt.weekday() == 6:
        nxt += timedelta(days=1)
    monday = day - timedelta(days=day.weekday())
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"⬅️ {prev:%d.%m}", callback_data=f"{prefix}:{eid}:d:{prev.isoformat()}"),
                InlineKeyboardButton(text=f"{nxt:%d.%m} ➡️", callback_data=f"{prefix}:{eid}:d:{nxt.isoformat()}"),
            ],
            [InlineKeyboardButton(text="🗓 Вся неделя", callback_data=f"{prefix}:{eid}:w:{monday.isoformat()}")],
            *_profile_row(prefix, eid),
        ]
    )


def entity_week_nav(prefix: str, eid: int, monday: date) -> InlineKeyboardMarkup:
    prev, nxt = monday - timedelta(days=7), monday + timedelta(days=7)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅️ Неделя назад", callback_data=f"{prefix}:{eid}:w:{prev.isoformat()}"),
                InlineKeyboardButton(text="Неделя вперёд ➡️", callback_data=f"{prefix}:{eid}:w:{nxt.isoformat()}"),
            ],
            *_profile_row(prefix, eid),
        ]
    )


def choice_list(items: list[tuple[str, str]], per_row: int = 1) -> InlineKeyboardMarkup:
    """items: (текст, callback_data)."""
    rows, row = [], []
    for text, data in items:
        row.append(InlineKeyboardButton(text=text, callback_data=data))
        if len(row) == per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


KIND_BITS = {"Лекция": 1, "Практика": 2, "Лабораторная": 4}


def subject_kb(idx: int, mask: int, present: list[str]) -> InlineKeyboardMarkup:
    titles = {"Лекция": "Лекции", "Практика": "Практики", "Лабораторная": "Лабораторные"}
    row = []
    for k in present:
        bit = KIND_BITS[k]
        on = bool(mask & bit)
        row.append(
            InlineKeyboardButton(text=f"{'✅' if on else '⬜'} {titles[k]}", callback_data=f"subj:{idx}:{mask ^ bit}")
        )
    rows = [row] if row else []
    rows.append([InlineKeyboardButton(text="⬅️ Все предметы", callback_data="subj:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --- личный кабинет (п. 37–50) ---

LK_SECTIONS = [
    ("📔 Дневник", "diary"),
    ("💬 Сообщения", "messages"),
    ("📁 Файлы группы", "files"),
    ("📒 Зачётка", "record_book"),
    ("⚠️ Задолженности", "debts"),
    ("🏆 Рейтинг", "rating"),
    ("💰 Стипендии", "scholarships"),
    ("📑 Приказы", "orders"),
    ("📚 Учебный план", "plan"),
    ("👤 Профиль", "profile"),
]


def lk_link_offer() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔗 Подключить кабинет", callback_data="lk:link")]]
    )


def lk_cabinet(auto_on: bool = False) -> InlineKeyboardMarkup:
    rows, row = [], []
    for title, name in LK_SECTIONS:
        row.append(InlineKeyboardButton(text=title, callback_data=f"lk:sec:{name}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="✅ Отметиться на паре", callback_data="lk:att")])
    auto = "✅ Автоотметка: вкл" if auto_on else "☑️ Автоотметка: выкл"
    rows.append([InlineKeyboardButton(text=auto, callback_data="lk:auto")])
    rows.append([InlineKeyboardButton(text="🔌 Отключить кабинет", callback_data="lk:unlink")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def lk_auto_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, включить автоотметку", callback_data="lk:auto:on")],
            [InlineKeyboardButton(text="Отмена", callback_data="lk:menu")],
        ]
    )


def lk_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ В кабинет", callback_data="lk:menu")]])


def lk_unlink_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔌 Да, отключить", callback_data="lk:unlink:yes")],
            [InlineKeyboardButton(text="Отмена", callback_data="lk:menu")],
        ]
    )
