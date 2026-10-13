"""Парсеры разделов lk.sut.ru (п. 37–49). Разметка — docs/recon.md, раздел 4."""

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from selectolax.lexbor import LexborHTMLParser, LexborNode

FILE_BASE = "https://lk.sut.ru/cabinet/"


def _t(node: LexborNode | None) -> str:
    return re.sub(r"\s+", " ", node.text(separator=" ")).strip() if node is not None else ""


def _dt(text: str) -> datetime | None:
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})\s+(\d{2}):(\d{2}):(\d{2})", text)
    if not m:
        return None
    d, mo, y, h, mi, s = map(int, m.groups())
    return datetime(y, mo, d, h, mi, s)


def _links(node: LexborNode) -> list[tuple[str, str]]:
    out = []
    for a in node.css("a[href]"):
        href = a.attributes.get("href") or ""
        if href and not href.startswith("javascript"):
            out.append((_t(a) or href.rsplit("/", 1)[-1], href if href.startswith("http") else FILE_BASE + href))
    return out


def _rows(tree: LexborHTMLParser, selector: str) -> list[list[str]]:
    table = tree.css_first(selector)
    if table is None:
        return []
    rows = []
    for tr in table.css("tr"):
        cells = [_t(td) for td in tr.css("td")]
        if cells and any(cells):
            rows.append(cells)
    return rows


# --- главная / профиль ---


@dataclass
class Profile:
    fio: str = ""
    fields: dict[str, str] = field(default_factory=dict)  # «Группа» -> «ИСТ-2633», …

    @property
    def group(self) -> str:
        return self.fields.get("Группа", "")


def parse_profile(html: str) -> Profile:
    tree = LexborHTMLParser(html)
    p = Profile()
    for tr in tree.css("table.profil tr, table tr"):
        th, td = tr.css_first("th"), tr.css_first("td")
        if th is None or td is None:
            continue
        label = _t(th).rstrip(":").strip()
        value = _t(td)
        if not label or not value or label == "Дата рождения":  # дату рождения не храним и не показываем
            continue
        if label == "ФИО":
            p.fio = value
        else:
            p.fields.setdefault(label, value)
    return p


# --- сообщения (п. 37) ---


@dataclass
class Message:
    id: int
    at: datetime | None
    subject: str
    sender: str
    files: list[tuple[str, str]]  # (имя, url)


def parse_messages(html: str) -> list[Message]:
    tree = LexborHTMLParser(html)
    out = []
    for tr in tree.css("#mytable tr[id^=tr_]"):
        mid = int(tr.attributes["id"].split("_")[1])
        tds = tr.css("td")
        if len(tds) < 4:
            continue
        out.append(
            Message(
                id=mid,
                at=_dt(_t(tds[0])),
                subject=_t(tds[1]),
                files=_links(tds[2]),
                sender=re.sub(r"\s*-\s*\(.*\)$", "", _t(tds[3])),
            )
        )
    return out


def parse_message_body(raw: str) -> tuple[str, bool]:
    """Ответ sendto2.php?prosmotr (JSON). Возвращает (текст, можно ли ответить)."""
    data = json.loads(raw)
    text = LexborHTMLParser(f"<div>{data.get('annotation') or ''}</div>").css_first("div").text(separator="\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip(), str(data.get("otvet", "0")) != "0"


# --- файлы группы (п. 38) ---


@dataclass
class GroupFile:
    id: int
    sender: str
    at: datetime | None
    subject: str
    text: str
    files: list[tuple[str, str]]
    unread: bool


def parse_group_files(html: str) -> list[GroupFile]:
    tree = LexborHTMLParser(html)
    out = []
    for tr in tree.css("#mytable tr[id^=tr_]"):
        tds = tr.css("td")
        if len(tds) < 6:
            continue
        out.append(
            GroupFile(
                id=int(tr.attributes["id"].split("_")[1]),
                sender=_t(tds[1]),
                at=_dt(_t(tds[2])),
                subject=_t(tds[3]),
                text=_t(tds[4]),
                files=_links(tds[5]),
                unread="bold" in (tr.attributes.get("style") or ""),
            )
        )
    return out


# --- дневник (п. 39) ---


@dataclass(frozen=True)
class Mark:
    day: date
    subject: str
    value: str  # «5», «Н», «Н, У» …


def parse_diary(html: str) -> list[Mark]:
    tree = LexborHTMLParser(html)
    table = tree.css_first("table.smalltab")
    if table is None:
        return []
    rows = table.css("tr")
    if not rows:
        return []
    subjects = [_t(c) for c in rows[0].css("th, td")]
    marks = []
    for tr in rows[1:]:
        d = tr.attributes.get("date1")
        if not d:
            continue
        day = date.fromisoformat(d)
        for j, td in enumerate(tr.css("td")):
            if j < 2 or j >= len(subjects):
                continue
            value = _t(td)
            if value:
                marks.append(Mark(day, subjects[j], value))
    return marks


# --- таблицы «как есть»: зачётка, план, приказы, стипендии, рейтинг ---


@dataclass
class RecordBook:
    course: str
    semester: str
    subject: str
    hours: str
    exam: str
    credit: str
    teacher: str


def parse_record_book(html: str) -> list[RecordBook]:
    out = []
    for cells in _rows(LexborHTMLParser(html), "table.simple-little-table"):
        if len(cells) >= 7:
            out.append(RecordBook(*cells[:7]))
    return out


@dataclass
class PlanItem:
    course: str
    semester: str
    code: str
    subject: str
    hours: str
    contact_hours: str
    control: list[str]  # «Экзамен», «Зачёт», …


_PLAN_CONTROL = ["Экзамен", "Зачёт", "Зачёт с оценкой", "Курсовой проект", "Курсовая работа"]


def parse_study_plan(html: str) -> list[PlanItem]:
    out = []
    for cells in _rows(LexborHTMLParser(html), "table.simple-little-table"):
        if len(cells) < 12:
            continue
        control = [name for name, v in zip(_PLAN_CONTROL, cells[7:12], strict=False) if v]
        out.append(PlanItem(cells[0], cells[1], cells[2], cells[3].strip(), cells[5], cells[6], control))
    return out


@dataclass
class Order:
    number: str
    date: str
    title: str
    comment: str


def parse_orders(html: str) -> list[Order]:
    return [Order(*c[:4]) for c in _rows(LexborHTMLParser(html), "table#mytable") if len(c) >= 4]


@dataclass
class Scholarship:
    order: str
    year: str
    title: str
    amount: str
    since: str
    till: str


def parse_scholarships(html: str) -> list[Scholarship]:
    return [Scholarship(*c[1:7]) for c in _rows(LexborHTMLParser(html), "table.simple-little-table") if len(c) >= 7]


RATING_COLUMNS = [
    "Факультет",
    "Курс",
    "Средний балл по зачётке",
    "Средний балл по диплому",
    "Средний балл за последний семестр",
    "Место по вузу",
    "Место по факультету",
    "Место по курсу",
]


def parse_rating(html: str) -> dict[str, str] | None:
    rows = [c for c in _rows(LexborHTMLParser(html), "table.simple-little-table") if len(c) >= 8]
    return dict(zip(RATING_COLUMNS, rows[0], strict=False)) if rows else None


# --- разделы-тексты: долги, аттестация, студсовет, справки ---


def parse_text_section(html: str) -> str:
    """Текст раздела без меню и форм — для «Задолженностей», «Аттестации», «Студсовета»."""
    tree = LexborHTMLParser(html)
    for sel in ("script", "style", "form", "select", "img"):
        for n in tree.css(sel):
            n.decompose()
    body = tree.body or tree.root
    text = body.text(separator="\n") if body is not None else ""
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def parse_debts(html: str) -> list[list[str]] | None:
    """None — задолженностей нет; иначе строки таблицы."""
    tree = LexborHTMLParser(html)
    if "Задолженность отсутствует" in html:
        return None
    return _rows(tree, "table") or [[parse_text_section(html)]]


# --- расписание ЛК с кнопкой «Начать занятие» (п. 35–36) ---


@dataclass
class LkLesson:
    rasp: str  # id занятия в ЛК (для кнопки отметки)
    time: str  # «1 (9:00-10:35)»
    subject: str
    room: str
    teacher: str
    started: bool  # занятие уже отмечено
    button_ready: bool  # кнопка отметки доступна сейчас


def parse_lk_schedule(html: str) -> list[LkLesson]:
    tree = LexborHTMLParser(html)
    table = tree.css_first("table.simple-little-table")
    if table is None:
        return []
    out = []
    for tr in table.css("tr"):
        tds = tr.css("td")
        if len(tds) < 5:
            continue
        knop = tr.css_first("[id^=knop]")
        rasp = knop.attributes["id"][4:] if knop is not None else ""
        if not rasp:
            continue
        text = _t(tds[1])
        out.append(
            LkLesson(
                rasp=rasp,
                time=_t(tds[0]),
                subject=text,
                room=_t(tds[3]),
                teacher=_t(tds[4]),
                started="занятие началось" in text or "Закончено" in _t(knop),
                button_ready="Отметиться" in _t(knop) or "Начать" in _t(knop),
            )
        )
    return out


def parse_mark_result(raw: str) -> str:
    """Ответ open=1/open=3 — JSON {data: html}. Возвращает текст состояния кнопки."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _t(LexborHTMLParser(raw).body) if raw else ""
    return re.sub(r"\s+", " ", LexborHTMLParser(f"<div>{data.get('data', '')}</div>").text()).strip()
