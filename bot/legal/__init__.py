"""Юридические документы бота (п. 69). Тексты — черновики, перед публичным запуском проверить у юриста."""

from dataclasses import dataclass
from pathlib import Path

_DIR = Path(__file__).parent


@dataclass(frozen=True)
class Document:
    code: str
    title: str
    version: str
    file: str

    @property
    def text(self) -> str:
        return (_DIR / self.file).read_text(encoding="utf-8")


# При изменении текста — поднять version: бот попросит всех принять новую редакцию.
DOCUMENTS = [
    Document("consent", "Согласие на обработку персональных данных", "1.0", "consent.md"),
    Document("privacy", "Политика обработки персональных данных", "1.0", "privacy.md"),
    Document("terms", "Правила использования", "1.0", "terms.md"),
]
BY_CODE = {d.code: d for d in DOCUMENTS}
