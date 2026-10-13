"""Текстовое оформление расписания (HTML-разметка Telegram)."""

from datetime import date, timedelta
from html import escape

from bot.services.schedule import Diff
from bot.services.sut_public.models import Lesson, Week

WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS_GEN = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]

MAX_LEN = 4000  # лимит Telegram — 4096


def kind_short(kind: str) -> str:
    k = kind.lower()
    if k.startswith("лек"):
        return "Лекция"
    if k.startswith("практ"):
        return "Практика"
    if k.startswith("лаб"):
        return "Лабораторная"
    return kind


def kind_mark(kind: str) -> str:
    k = kind.lower()
    if k.startswith("лек"):
        return "🟦"
    if k.startswith("практ"):
        return "🟩"
    if k.startswith("лаб"):
        return "🟥"
    return "⬜"


def room_str(l: Lesson) -> str:
    if not l.room:
        return ""
    return f"ауд. {l.room}" + (f" ({l.building})" if l.building else "")


def day_title(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS_GEN[d.month - 1]}"


def week_label(week: Week) -> str:
    if week.parity and week.number:
        return f"{week.parity} неделя ({week.number})"
    return ""


def _lesson_block(l: Lesson) -> str:
    lines = [
        f"{kind_mark(l.kind)} <b>{escape(l.pair)}</b> · {l.start}–{l.end}",
        f"<b>{escape(l.subject)}</b>",
        " · ".join(p for p in (kind_short(l.kind), escape(room_str(l))) if p),
    ]
    if l.teachers_short:
        lines.append(f"<i>{escape(l.teachers_short)}</i>")
    return "\n".join(lines)


def render_day(group_name: str, week: Week, day: date) -> str:
    head = f"<b>📅 {day_title(day)}</b>\n{escape(group_name)}"
    if label := week_label(week):
        head += f" · {label}"
    lessons = week.by_day(day)
    if not lessons:
        return head + "\n\nПар нет 🎉"
    return head + "\n\n" + "\n\n".join(_lesson_block(l) for l in lessons)


def _lesson_line(l: Lesson) -> str:
    tail = ", ".join(p for p in (room_str(l), l.teachers_short) if p)
    return f"{kind_mark(l.kind)} {escape(l.pair)} {l.start} {escape(l.subject)}" + (
        f" — {escape(tail)}" if tail else ""
    )


def render_week(group_name: str, week: Week) -> str:
    out = [
        f"<b>🗓 Неделя с {week.monday:%d.%m}</b>\n{escape(group_name)}"
        + (f" · {week_label(week)}" if week_label(week) else "")
    ]
    for i in range(6):
        d = week.monday + timedelta(days=i)
        lessons = week.by_day(d)
        block = f"<b>{WEEKDAYS_SHORT[i]}, {d:%d.%m}</b>\n"
        block += "\n".join(_lesson_line(l) for l in lessons) if lessons else "— пар нет"
        out.append(block)
    return "\n\n".join(out)


def render_period(group_name: str, lessons: list[Lesson], start: date, end: date) -> list[str]:
    """Компактный вид на месяц; возвращает список сообщений с учётом лимита длины."""
    by_day: dict[date, list[Lesson]] = {}
    for l in lessons:
        by_day.setdefault(l.day, []).append(l)
    blocks = []
    for d in sorted(by_day):
        items = sorted(by_day[d], key=lambda l: (l.start, l.subject))
        seen, parts = set(), []
        for l in items:  # подгруппы в одно время схлопываем
            k = (l.pair, l.subject.split(" (")[0], l.kind)
            if k in seen:
                continue
            seen.add(k)
            kind = kind_short(l.kind)
            suffix = "" if kind == "Практика" else f" ({kind.lower()[:3]}.)"
            parts.append(f"{escape(l.pair)}·{escape(k[1])}{suffix}")
        blocks.append(f"<b>{WEEKDAYS_SHORT[d.weekday()]} {d:%d.%m}</b>: " + "; ".join(parts))
    header = f"<b>📆 {start:%d.%m} — {end:%d.%m}</b>\n{escape(group_name)}\n"
    if not blocks:
        return [header + "\nЗанятий нет"]
    return split_messages(header, blocks)


def split_messages(header: str, blocks: list[str], sep: str = "\n") -> list[str]:
    msgs, cur = [], header
    for b in blocks:
        if len(cur) + len(b) + len(sep) > MAX_LEN:
            msgs.append(cur)
            cur = ""
        cur += (sep if cur else "") + b
    if cur:
        msgs.append(cur)
    return msgs


def render_diff(group_name: str, diff: Diff) -> str:
    out = [f"<b>🔔 Изменения в расписании {escape(group_name)}</b>"]
    for d in diff.days:
        lines = [f"<b>{WEEKDAYS_SHORT[d.weekday()]}, {d:%d.%m}</b>"]
        lines += ["➖ <s>" + _lesson_line(l) + "</s>" for l in diff.removed if l.day == d]
        lines += ["➕ " + _lesson_line(l) for l in diff.added if l.day == d]
        out.append("\n".join(lines))
    text = "\n\n".join(out)
    return text if len(text) <= MAX_LEN else text[: MAX_LEN - 20] + "\n…"
