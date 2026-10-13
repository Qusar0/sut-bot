"""Расписание дня картинкой (п. 6). Pillow, без браузера: ~50 мс на картинку."""

import io
import os
from datetime import date
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from bot.render.text import MONTHS_GEN, WEEKDAYS, kind_short, room_short
from bot.services.sut_public.models import Lesson

S = 2  # масштаб: рисуем в 2× для чёткости на телефонах
W = 540 * S
PAD = 24 * S
GAP = 12 * S

INK = (24, 28, 36)
MUTED = (110, 117, 130)
LINE = (226, 230, 236)
BG = (255, 255, 255)
BRAND = (255, 140, 26)

# тип занятия -> (основной цвет, фон плашки)
PALETTE = {
    "Лекция": ((47, 111, 235), (234, 241, 255)),
    "Практика": ((31, 157, 85), (231, 246, 236)),
    "Лабораторная": ((229, 72, 77), (253, 236, 236)),
}
OTHER = ((120, 126, 138), (241, 243, 246))

_FONT_CANDIDATES = {
    False: [
        os.environ.get("FONT_REGULAR", ""),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ],
    True: [
        os.environ.get("FONT_BOLD", ""),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ],
}


@lru_cache(maxsize=32)
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES[bold]:
        if path and os.path.exists(path):
            return ImageFont.truetype(path, size * S)
    raise RuntimeError("не найден шрифт с кириллицей: установите DejaVu или задайте FONT_REGULAR/FONT_BOLD")


def _wrap(text: str, f: ImageFont.FreeTypeFont, width: int, max_lines: int = 3) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if f.getlength(trial) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while f.getlength(lines[-1] + "…") > width and " " in lines[-1]:
            lines[-1] = lines[-1].rsplit(" ", 1)[0]
        lines[-1] += "…"
    return lines


def _h(f: ImageFont.FreeTypeFont) -> int:
    a, d = f.getmetrics()
    return a + d


Counter = dict[tuple, tuple[int, int]]  # (день, начало, предмет, тип) -> (номер, всего)


def counter_key(l: Lesson) -> tuple:
    return (l.day, l.start, l.subject.split(" (")[0], kind_short(l.kind))


CARD_X = PAD + 92 * S
CARD_W = W - CARD_X - PAD
INNER = 16 * S


def _card_lines(l: Lesson) -> tuple[list[str], list[str]]:
    title = _wrap(l.subject, font(18, True), CARD_W - 2 * INNER)
    meta = []
    if l.room:
        meta.append(f"ауд. {room_short(l)}")
    if l.teachers_short:
        meta += _wrap(l.teachers_short, font(14), CARD_W - 2 * INNER, max_lines=2)
    return title, meta


def _card_height(l: Lesson) -> int:
    title, meta = _card_lines(l)
    return (
        INNER + _h(font(13, True)) + 8 * S + len(title) * _h(font(18, True)) + 6 * S + len(meta) * _h(font(14)) + INNER
    )


def render_day_image(
    group_name: str, day: date, lessons: list[Lesson], week_label: str = "", counters: Counter | None = None
) -> bytes:
    counters = counters or {}
    # слоты: подгруппы одной пары рисуем друг под другом в одном слоте
    slots: dict[tuple[str, str, str], list[Lesson]] = {}
    for l in sorted(lessons, key=lambda x: (x.start, x.subject)):
        slots.setdefault((l.pair, l.start, l.end), []).append(l)

    header_h = PAD + _h(font(30, True)) + 6 * S + _h(font(16)) + 18 * S
    body_h = sum(sum(_card_height(l) for l in ls) + GAP * (len(ls) - 1) + GAP for ls in slots.values())
    if not slots:
        body_h = 120 * S
    height = header_h + body_h + PAD

    img = Image.new("RGB", (W, height), BG)
    d = ImageDraw.Draw(img)

    # шапка
    y = PAD
    d.text((PAD, y), group_name, font=font(30, True), fill=INK)
    # «листок календаря» с числом и месяцем
    bw, bh = 56 * S, 60 * S
    bx, by = W - PAD - bw, y
    d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=12 * S, fill=BRAND)
    d.text((bx + bw / 2, by + 6 * S), MONTHS_GEN[day.month - 1][:3].upper(), font=font(11, True), fill=BG, anchor="ma")
    d.text((bx + bw / 2, by + bh - 6 * S), str(day.day), font=font(24, True), fill=BG, anchor="md")
    y += _h(font(30, True)) + 6 * S
    sub = f"{WEEKDAYS[day.weekday()]}, {day.day} {MONTHS_GEN[day.month - 1]} {day.year}"
    if week_label:
        sub += f" · {week_label}"
    d.text((PAD, y), sub, font=font(16), fill=MUTED)
    y += _h(font(16)) + 10 * S
    d.line((PAD, y, W - PAD, y), fill=LINE, width=2 * S)
    y += 8 * S

    if not slots:
        d.text((PAD, y + 40 * S), "Пар нет", font=font(22, True), fill=MUTED)

    for (pair, start, end), items in slots.items():
        y_slot = y + GAP // 2
        color = PALETTE.get(kind_short(items[0].kind), OTHER)[0]
        # номер пары в кружке и время
        r = 18 * S
        cx, cy = PAD + r, y_slot + r + 4 * S
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
        num_f = font(16 if len(pair) <= 1 else 12, True)
        d.text((cx, cy), pair, font=num_f, fill=BG, anchor="mm")
        d.text((PAD, cy + r + 8 * S), start, font=font(15, True), fill=INK)
        d.text((PAD, cy + r + 8 * S + _h(font(15, True))), end, font=font(13), fill=MUTED)

        for l in items:
            main, tint = PALETTE.get(kind_short(l.kind), OTHER)
            h = _card_height(l)
            d.rounded_rectangle((CARD_X, y_slot, CARD_X + CARD_W, y_slot + h), radius=14 * S, fill=tint)
            d.rounded_rectangle((CARD_X, y_slot, CARD_X + 5 * S, y_slot + h), radius=3 * S, fill=main)
            ty = y_slot + INNER
            tag = kind_short(l.kind)
            d.text((CARD_X + INNER, ty), tag.upper(), font=font(13, True), fill=main)
            if (cnt := counters.get(counter_key(l))) is not None:
                label = f"{cnt[0]} из {cnt[1]}"
                d.text((CARD_X + CARD_W - INNER, ty), label, font=font(13), fill=MUTED, anchor="ra")
            ty += _h(font(13, True)) + 8 * S
            title, meta = _card_lines(l)
            for line in title:
                d.text((CARD_X + INNER, ty), line, font=font(18, True), fill=INK)
                ty += _h(font(18, True))
            ty += 6 * S
            for line in meta:
                d.text((CARD_X + INNER, ty), line, font=font(14), fill=MUTED)
                ty += _h(font(14))
            y_slot += h + GAP
        y = y_slot

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def lesson_counters(semester_lessons: list[Lesson]) -> Counter:
    """Порядковый номер занятия среди занятий того же предмета и типа за семестр («6 из 18»)."""
    groups: dict[tuple[str, str], list[tuple]] = {}
    seen = set()
    for l in sorted(semester_lessons, key=lambda x: (x.day, x.start)):
        k = counter_key(l)
        if k in seen:  # подгруппы одного занятия считаем один раз
            continue
        seen.add(k)
        groups.setdefault((k[2], k[3]), []).append(k)
    out: Counter = {}
    for keys in groups.values():
        for i, k in enumerate(keys, start=1):
            out[k] = (i, len(keys))
    return out
