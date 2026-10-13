from dataclasses import asdict, dataclass, field
from datetime import date


@dataclass(frozen=True)
class Lesson:
    day: date
    pair: str  # "1".."7" или "ФЗ"
    start: str  # "09:00"
    end: str  # "10:35"
    subject: str
    kind: str  # "Лекция", "Практические занятия", ...
    room: str  # "303", "Динамит"
    building: str  # "Б22/2", "Ч13В"
    teachers: tuple[str, ...]  # полные ФИО
    teachers_short: str  # "Кокорин М.С."

    def key(self) -> tuple:
        return (self.day.isoformat(), self.pair, self.subject, self.kind, self.room, self.building, self.teachers)

    def signature(self) -> tuple:
        """То, что видит студент. Если у отменённой и добавленной пары подписи совпали —
        для студента ничего не изменилось (напр. поменялось только полное ФИО, а не «Климов А.»)."""
        import re

        def norm(s: str) -> str:
            return re.sub(r"\s+", " ", (s or "")).strip().lower()

        return (
            self.day.isoformat(),
            norm(self.pair),
            self.start,
            self.end,
            norm(self.subject),
            norm(self.kind),
            norm(self.room),
            norm(self.building),
            norm(self.teachers_short),
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["day"] = self.day.isoformat()
        d["teachers"] = list(self.teachers)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Lesson":
        return cls(**{**d, "day": date.fromisoformat(d["day"]), "teachers": tuple(d["teachers"])})


@dataclass
class Week:
    group_id: int
    monday: date
    number: int | None  # номер учебной недели
    parity: str | None  # "Чётная" / "Нечётная"
    lessons: list[Lesson] = field(default_factory=list)

    def by_day(self, day: date) -> list[Lesson]:
        return sorted((l for l in self.lessons if l.day == day), key=lambda l: (l.start, l.subject))


@dataclass(frozen=True)
class Group:
    id: int
    name: str
    faculty: str
