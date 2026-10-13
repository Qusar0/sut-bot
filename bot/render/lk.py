"""Оформление разделов личного кабинета для Telegram (п. 37–50)."""

from datetime import datetime
from html import escape

from bot.render.text import MAX_LEN
from bot.services.lk import parser as P

LIMIT = MAX_LEN


def _dt(value) -> str:
    if isinstance(value, str) and value:
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime("%d.%m.%Y %H:%M") if isinstance(value, datetime) else ""


def _clip(text: str) -> str:
    return text if len(text) <= LIMIT else text[: LIMIT - 1] + "…"


def render_messages(items: list[P.Message]) -> str:
    if not items:
        return "<b>💬 Сообщения</b>\n\nПусто."
    lines = ["<b>💬 Сообщения</b>"]
    for m in items[:20]:
        head = f"\n<b>{escape(m.subject or 'Без темы')}</b>"
        meta = " · ".join(p for p in (escape(m.sender), _dt(m.at)) if p)
        lines.append(head + (f"\n<i>{meta}</i>" if meta else ""))
        for name, url in m.files:
            lines.append(f'📎 <a href="{escape(url)}">{escape(name)}</a>')
    return _clip("\n".join(lines))


def render_files(items: list[P.GroupFile]) -> str:
    if not items:
        return "<b>📁 Файлы группы</b>\n\nПусто."
    lines = ["<b>📁 Файлы группы</b>"]
    for f in items[:20]:
        mark = "🆕 " if f.unread else ""
        lines.append(f"\n{mark}<b>{escape(f.subject or '—')}</b>")
        meta = " · ".join(p for p in (escape(f.sender), _dt(f.at)) if p)
        if meta:
            lines.append(f"<i>{meta}</i>")
        if f.text:
            lines.append(escape(f.text))
        for name, url in f.files:
            lines.append(f'📎 <a href="{escape(url)}">{escape(name)}</a>')
    return _clip("\n".join(lines))


def render_diary(items: list[P.Mark]) -> str:
    if not items:
        return "<b>📔 Дневник</b>\n\nОценок и отметок пока нет."
    recent = sorted(items, key=lambda m: m.day, reverse=True)[:30]
    lines = ["<b>📔 Дневник</b> <i>(последнее)</i>"]
    cur = None
    for m in recent:
        if m.day != cur:
            cur = m.day
            lines.append(f"\n<b>{m.day:%d.%m}</b>")
        lines.append(f"• {escape(m.subject)}: <b>{escape(m.value)}</b>")
    return _clip("\n".join(lines))


def render_record_book(items: list[P.RecordBook]) -> str:
    if not items:
        return "<b>📒 Зачётка</b>\n\nПусто."
    lines = ["<b>📒 Зачётка</b>"]
    for r in items:
        grade = r.exam or r.credit
        lines.append(
            f"• {escape(r.subject)} — <b>{escape(grade)}</b>" + (f" <i>({escape(r.teacher)})</i>" if r.teacher else "")
        )
    return _clip("\n".join(lines))


def render_orders(items: list[P.Order]) -> str:
    if not items:
        return "<b>📑 Приказы</b>\n\nПусто."
    lines = ["<b>📑 Приказы</b>"]
    for o in items[:30]:
        lines.append(f"\n<b>{escape(o.title)}</b>\n№{escape(o.number)} от {escape(o.date)}")
        if o.comment:
            lines.append(f"<i>{escape(o.comment)}</i>")
    return _clip("\n".join(lines))


def render_scholarships(items: list[P.Scholarship]) -> str:
    if not items:
        return "<b>💰 Стипендии</b>\n\nНазначений нет."
    lines = ["<b>💰 Стипендии</b>"]
    for sch in items:
        lines.append(f"• {escape(sch.title)} — <b>{escape(sch.amount)} ₽</b> ({escape(sch.since)}–{escape(sch.till)})")
    return _clip("\n".join(lines))


def render_rating(data: dict | None) -> str:
    if not data:
        return "<b>🏆 Рейтинг</b>\n\nДанных нет."
    lines = ["<b>🏆 Рейтинг</b>"]
    for k, v in data.items():
        if v:
            lines.append(f"• {escape(k)}: <b>{escape(v)}</b>")
    return _clip("\n".join(lines))


def render_plan(items: list[P.PlanItem]) -> str:
    if not items:
        return "<b>📚 Учебный план</b>\n\nПусто."
    lines = ["<b>📚 Учебный план</b>"]
    cur = None
    for it in items:
        sem = f"{it.course} курс, {it.semester} семестр"
        if sem != cur:
            cur = sem
            lines.append(f"\n<b>{sem}</b>")
        control = ", ".join(it.control) if it.control else ""
        lines.append(f"• {escape(it.subject)}" + (f" <i>({escape(control)})</i>" if control else ""))
    return _clip("\n".join(lines))


def render_text(title: str, text: str) -> str:
    return _clip(f"<b>{escape(title)}</b>\n\n{escape(text) if text else 'Пусто.'}")


def render_debts(rows) -> str:
    if rows is None:
        return "<b>⚠️ Задолженности</b>\n\n✅ Задолженностей нет."
    lines = ["<b>⚠️ Задолженности</b>"]
    for row in rows:
        lines.append("• " + escape(" · ".join(c for c in row if c)))
    return _clip("\n".join(lines))


# --- уведомления о новом из ЛК (п. 52–56, 58) ---

NEWS_TITLES = {
    "diary": "📔 Новые оценки/отметки",
    "messages": "💬 Новое сообщение от преподавателя",
    "files": "📁 Новый файл группы",
    "debts": "⚠️ Изменения в задолженностях",
    "orders": "📑 Новый приказ",
    "scholarships": "💰 Изменения по стипендии",
    "rating": "🏆 Обновился рейтинг",
}


def render_news(section: str, items: list) -> str | None:
    """Короткое уведомление о новом в разделе. None — показывать нечего."""
    title = NEWS_TITLES.get(section)
    if not title or not items:
        return None
    lines = [f"<b>{title}</b>"]
    for it in items[:10]:
        if section == "diary":
            lines.append(f"• {escape(it.get('subject', ''))}: <b>{escape(it.get('value', ''))}</b>")
        elif section in ("messages", "files"):
            who = it.get("sender", "")
            lines.append(f"• {escape(it.get('subject') or '—')}" + (f" <i>({escape(who)})</i>" if who else ""))
        elif section == "orders":
            lines.append(f"• {escape(it.get('title', ''))}")
        else:
            lines.append("• " + escape(str(it)[:80]))
    return _clip("\n".join(lines))
