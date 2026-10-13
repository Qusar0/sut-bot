from pathlib import Path

from bot.render.directory import render_profile
from bot.services.staff import StaffService
from bot.services.sut_public import staff as S

FIX = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_links():
    faculties = S.parse_faculty_links(read("faculties.html"))
    assert "/education/fakulteti-i-instituti/itpi" in faculties
    deps = S.parse_department_links(read("faculty.html"), "/education/fakulteti-i-instituti/itpi")
    assert "/education/fakulteti-i-instituti/itpi/ikd" in deps
    assert not any("dekanat" in d or "news" in d or "about" in d for d in deps)


def test_staff_list():
    cards = S.parse_staff_list(read("staff_list.html"))
    gromov = next(c for c in cards if c.full_name == "Громов Владислав Витальевич")
    assert gromov.position == "кандидат технических наук, доцент кафедры ИКД"
    assert gromov.url.startswith("https://www.sut.ru/education/")


def test_profile():
    p = S.parse_profile(read("staff_profile.html"), "https://www.sut.ru/x")
    assert p.full_name == "Громов Владислав Витальевич"
    assert p.contacts["Адрес"].endswith("каб. 232/2")
    assert "E-mail" in p.contacts and "Телефон" in p.contacts
    assert "Базы данных" in p.interests
    assert p.photo.startswith("https://www.sut.ru/new_site/images/teacher/")
    text = render_profile(p, ["Информатика"])
    assert "Ведёт у вашей группы:</b> Информатика" in text and len(text) < 1024


class FakeClient:
    def __init__(self):
        self.calls = 0

    async def get_url(self, url: str, background: bool = True) -> str:
        self.calls += 1
        if url.endswith("fakulteti-i-instituti"):
            return read("faculties.html").replace("/ikss'", "/itpi'")  # в тесте обходим один факультет
        if url.endswith("/itpi"):
            return read("faculty.html")
        if url.endswith("/ikd/prepodavatelskiy-sostav"):
            return read("staff_list.html")
        if "777-gromov" in url or url.endswith("/gromova-test-testovna"):
            return read("staff_profile.html")
        raise RuntimeError("404")


async def test_staff_service():
    from bot.db.base import init_db

    await init_db()
    client = FakeClient()
    svc = StaffService(client)
    assert await svc.refresh_lists() >= 10
    p = await svc.profile("Громов Владислав Витальевич")
    assert p and p.contacts["Адрес"].endswith("232/2")
    calls = client.calls
    assert (await svc.profile("громов владислав витальевич")).full_name  # из кэша, без запроса
    assert client.calls == calls
    assert await svc.profile("Несуществующий Преподаватель") is None


async def test_fuzzy_match():
    from bot.db.base import init_db

    await init_db()
    svc = StaffService(FakeClient())
    await svc.refresh_lists()
    from bot.db.base import Session

    async with Session() as s:
        assert (await svc._find(s, "Климов Алексей -")).full_name == "Климов Алексей Михайлович"
        assert (await svc._find(s, "Громов В. В.")).full_name == "Громов Владислав Витальевич"
        assert await svc._find(s, "Громов") is None  # одной фамилии мало


def test_clean_person():
    from bot.services.directory import short_name
    from bot.services.sut_public.parser import clean_person

    assert clean_person("Климов Алексей -") == "Климов Алексей"
    assert short_name("Климов Алексей -") == "Климов А."


def test_slug_candidates():
    assert S.slug_candidates("Татаренков Дмитрий Александрович") == ["tatarenkov-dmitriy-aleksandrovich"]
    assert S.slug_candidates("Климов Алексей Михайлович") == ["klimov-aleksey-mihaylovich"]
    assert S.slug_candidates("Громов Владислав Витальевич") == ["gromov-vladislav-vitalevich"]


async def test_probe_root_requires_name_match():
    from bot.db.base import init_db

    await init_db()
    svc = StaffService(FakeClient())
    # страница по адресу есть, но на ней другой человек — не подставляем
    assert await svc.profile("Громова Тест Тестовна") is None
