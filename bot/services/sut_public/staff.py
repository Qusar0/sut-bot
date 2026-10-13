"""Профили преподавателей с сайта sut.ru (п. 14).

Факультет → кафедры → «Преподавательский состав» → карточки → страница профиля.
"""

import re
from dataclasses import asdict, dataclass, field

from selectolax.lexbor import LexborHTMLParser

SITE = "https://www.sut.ru"
FACULTIES_PATH = "/education/fakulteti-i-instituti"
# Разделы факультета, которые не являются кафедрами
_NOT_DEPARTMENT = re.compile(r"(about|dekanat|news|kontakt|abitur|istoriya|struktura)", re.I)


def _t(node) -> str:
    return re.sub(r"\s+", " ", node.text(separator=" ")).strip() if node is not None else ""


def _abs(href: str) -> str:
    return href if href.startswith("http") else SITE + href


def parse_faculty_links(html: str) -> list[str]:
    paths = re.findall(r"href=['\"](" + re.escape(FACULTIES_PATH) + r"/[a-z0-9-]+)['\"]", html)
    return sorted(set(paths))


def parse_department_links(html: str, faculty_path: str) -> list[str]:
    paths = re.findall(r"href=['\"](" + re.escape(faculty_path) + r"/[a-z0-9-]+)['\"]", html)
    return sorted({p for p in paths if not _NOT_DEPARTMENT.search(p.rsplit("/", 1)[1])})


@dataclass
class StaffCard:
    full_name: str
    position: str
    url: str


def parse_staff_list(html: str) -> list[StaffCard]:
    tree = LexborHTMLParser(html)
    cards = []
    for a in tree.css("a.teacher_card[href]"):
        name = _t(a.css_first("h4"))
        if not name:
            continue
        pos = a.css_first("p")
        position = re.sub(r"\s+", " ", pos.text(separator=", ")).strip(" ,") if pos is not None else ""
        cards.append(StaffCard(full_name=name, position=position, url=_abs(a.attributes["href"])))
    return cards


@dataclass
class Profile:
    full_name: str
    position: str = ""
    contacts: dict[str, str] = field(default_factory=dict)  # «Адрес», «E-mail», «Телефон»
    interests: list[str] = field(default_factory=list)
    education: str = ""
    photo: str = ""
    url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def parse_profile(html: str, url: str = "") -> Profile:
    tree = LexborHTMLParser(html)
    p = Profile(full_name=_t(tree.css_first("h1")), position=_t(tree.css_first(".vt63")), url=url)

    for block in tree.css(".vt67"):
        labels = block.css(".vt68")
        values = block.css(".vt69")
        for label, value in zip(labels, values, strict=False):
            key = _t(label).rstrip(":")
            val = _t(value)
            if key and val and key != "Соцсети":
                p.contacts[key] = val

    p.interests = [_t(n) for n in tree.css(".vt73 .vt74") if _t(n)]

    img = tree.css_first(".vt64 img")
    if img is not None and img.attributes.get("src"):
        p.photo = _abs(img.attributes["src"])

    body = tree.css_first(".vt4")
    if body is not None:
        text = body.text(separator="\n")
        m = re.search(r"Образование\s*\n+(.+?)(?:\n\s*\n|$)", text, re.S)
        if m:
            p.education = re.sub(r"\s+", " ", m.group(1)).strip()
    return p


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
}  # fmt: skip


def slug_candidates(full_name: str) -> list[str]:
    """Адреса профиля в корне сайта, как их делает sut.ru: «Татаренков Дмитрий Александрович» →
    tatarenkov-dmitriy-aleksandrovich. Для неоднозначных букв — запасной вариант."""
    base = "".join(_TRANSLIT.get(ch, ch) for ch in full_name.lower())
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    variants = [base]
    alt = base.replace("c", "ts").replace("tsh", "ch") if "ц" in full_name.lower() else None
    if alt and alt not in variants:
        variants.append(alt)
    return variants
