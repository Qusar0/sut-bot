"""Текстовое оформление расписания (HTML-разметка Telegram)."""

import re
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
LEGEND = "🟦 лекция  🟩 практика  🟥 лабораторная"


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


_MAIN_CAMPUS = re.compile(r"^Б22/(\d)$")


def room_short(l: Lesson) -> str:
    """«303» + «Б22/2» → «303/2» (как пишут в вузе); прочие корпуса — через пробел."""
    if not l.room:
        return ""
    if m := _MAIN_CAMPUS.match(l.building):
        return f"{l.room}/{m.group(1)}"
    if l.building and l.building not in l.room:
        return f"{l.room} · {l.building}"
    return l.room


def day_title(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS_GEN[d.month - 1]}"


def short_date(d: date) -> str:
    return f"{d.day} {MONTHS_GEN[d.month - 1][:3]}"


def week_label(week: Week) -> str:
    if week.parity and week.number:
        return f"{week.parity.lower()} неделя ({week.number})"
    return ""


def _details(l: Lesson) -> str:
    return " · ".join(escape(p) for p in (room_short(l), l.teachers_short) if p)


# --- день ---


def _lesson_body(l: Lesson) -> str:
    lines = [
        f"{kind_mark(l.kind)} <b>{escape(l.subject)}</b>",
        escape(kind_short(l.kind)) + (f" · ауд. {escape(room_short(l))}" if l.room else ""),
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
    # Подгруппы в одно и то же время — под одним заголовком пары
    slots: dict[tuple[str, str, str], list[Lesson]] = {}
    for l in lessons:
        slots.setdefault((l.pair, l.start, l.end), []).append(l)
    blocks = []
    for (pair, start, end), items in slots.items():
        title = f"{pair} пара" if pair.isdigit() else pair
        body = "\n\n".join(_lesson_body(l) for l in items)
        blocks.append(f"<b>{escape(title)}</b> · {start}–{end}\n{body}")
    return head + "\n\n" + "\n\n".join(blocks)


# --- неделя ---


def _lesson_line(l: Lesson) -> str:
    line = f"{kind_mark(l.kind)} <code>{l.start}</code> {escape(l.subject)}"
    if details := _details(l):
        line += f"\n      └ {details}"
    return line


def render_week(group_name: str, week: Week) -> str:
    end = week.monday + timedelta(days=5)
    head = f"<b>🗓 {short_date(week.monday)} — {short_date(end)}</b>\n{escape(group_name)}"
    if label := week_label(week):
        head += f" · {label}"
    out = [head]
    for i in range(6):
        d = week.monday + timedelta(days=i)
        lessons = week.by_day(d)
        block = f"<b>{WEEKDAYS[i]}, {d.day}</b>\n"
        block += "\n".join(_lesson_line(l) for l in lessons) if lessons else "<i>пар нет</i>"
        out.append(block)
    return "\n\n".join(out)


# --- месяц ---


def _day_summary(d: date, lessons: list[Lesson]) -> str:
    items = sorted(lessons, key=lambda l: (l.start, l.subject))
    seen, parts = set(), []
    for l in items:  # подгруппы одного предмета в одно время схлопываем
        k = (l.start, l.subject.split(" (")[0], kind_short(l.kind))
        if k not in seen:
            seen.add(k)
            parts.append(f"{kind_mark(l.kind)} {escape(k[1])}")
    span = f"{items[0].start}–{items[-1].end}"
    return f"<b>{WEEKDAYS_SHORT[d.weekday()]} {d.day:02d}</b>  <code>{span}</code>\n" + "\n".join(parts)


def render_period(group_name: str, weeks: list[Week], start: date, end: date) -> list[str]:
    """Расписание на период, сгруппированное по неделям; список сообщений с учётом лимита длины."""
    header = f"<b>📆 {short_date(start)} — {short_date(end)}</b> · {escape(group_name)}\n<i>{LEGEND}</i>"
    blocks: list[str] = []
    for w in weeks:
        days = []
        for i in range(6):
            d = w.monday + timedelta(days=i)
            if start <= d <= end and (lessons := w.by_day(d)):
                days.append(_day_summary(d, lessons))
        if not days:
            continue
        title = f"Неделя {w.number}" if w.number else f"Неделя с {short_date(w.monday)}"
        if w.parity:
            title += f" · {w.parity.lower()}"
        blocks.append(f"<b>━━ {title} ━━</b>\n\n" + "\n\n".join(days))
    if not blocks:
        return [header + "\n\nЗанятий нет"]
    return split_messages(header, blocks, sep="\n\n")


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


# --- изменения ---


def _change_detail(old: Lesson, new: Lesson) -> str:
    """Что именно поменялось в паре — только изменившееся (препод./аудитория/вид)."""
    parts = []
    if old.teachers_short != new.teachers_short:
        o = [t.strip() for t in old.teachers_short.split(";") if t.strip()]
        n = [t.strip() for t in new.teachers_short.split(";") if t.strip()]
        gone, came = [t for t in o if t not in n], [t for t in n if t not in o]
        if gone or came:
            parts.append(f"препод.: {', '.join(gone) or '—'} → {', '.join(came) or '—'}")
    if old.room != new.room:
        parts.append(f"ауд.: {old.room or '—'} → {new.room or '—'}")
    if old.kind != new.kind:
        parts.append(f"{old.kind} → {new.kind}")
    return escape("; ".join(parts)) if parts else _details(new)


def render_diff(group_name: str, diff: Diff) -> str:
    out = [f"<b>🔔 Изменения в расписании</b> · {escape(group_name)}"]
    for d in diff.days:
        lines = [f"<b>{day_title(d)}</b>"]
        for o, n in diff.changed:
            if n.day == d:
                lines.append(f"✏️ {n.start} {escape(n.subject)} <i>{_change_detail(o, n)}</i>")
        for l in diff.removed:
            if l.day == d:
                lines.append(f"➖ <s>{l.start} {escape(l.subject)}</s> <i>{_details(l)}</i>")
        for l in diff.added:
            if l.day == d:
                lines.append(f"➕ {l.start} {escape(l.subject)} <i>{_details(l)}</i>")
        out.append("\n".join(lines))
    text = "\n\n".join(out)
    return text if len(text) <= MAX_LEN else text[: MAX_LEN - 20] + "\n…"


# --- напоминание (п. 51) ---


def render_reminder(lessons: list[Lesson], minutes: int | None) -> str:
    """«Через 15 минут» + пары, которые начинаются (подгруппы — списком).

    minutes=None — рассылка большая и начата заранее: пишем точное время начала, а не «через N минут».
    """
    first = lessons[0]
    if minutes is None:
        head = f"⏰ <b>Скоро пара</b> · начало в {first.start}"
    else:
        head = f"⏰ <b>Через {minutes} мин</b> · {first.start}–{first.end}"
    items = []
    for l in lessons:
        line = f"{kind_mark(l.kind)} <b>{escape(l.subject)}</b>"
        if details := _details(l):
            line += f"\n      └ {details}"
        items.append(line)
    return head + "\n\n" + "\n".join(items)


def render_diff_short(diff: Diff, limit: int = 900) -> str:
    """Короткая сводка изменений для подписи к PDF (лимит подписи Telegram — 1024 символа)."""
    lines = []
    for d in diff.days:
        rem = [l for l in diff.removed if l.day == d]
        add = [l for l in diff.added if l.day == d]
        chg = [n for o, n in diff.changed if n.day == d]
        parts = (
            [f"✏️ {n.start} {escape(n.subject)}" for n in chg]
            + [f"➖ {l.start} {escape(l.subject)}" for l in rem]
            + [f"➕ {l.start} {escape(l.subject)}" for l in add]
        )
        lines.append(f"<b>{WEEKDAYS_SHORT[d.weekday()]} {d:%d.%m}</b>: " + "; ".join(parts))
    text = "\n".join(lines)
    return text if len(text) <= limit else text[: limit - 1] + "…"
