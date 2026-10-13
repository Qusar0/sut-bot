from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from bot.db.base import Base


class User(Base):
    __tablename__ = "users"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    group_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("groups.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    notify_tomorrow: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_week: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_changes: Mapped[bool] = mapped_column(Boolean, default=True)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)  # пользователь заблокировал бота


class Consent(Base):
    """Факт принятия документа определённой редакции (п. 69)."""

    __tablename__ = "consents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), index=True)
    doc: Mapped[str] = mapped_column(String(32))
    version: Mapped[str] = mapped_column(String(16))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # id на sut.ru
    name: Mapped[str] = mapped_column(String(64), index=True)
    faculty: Mapped[str] = mapped_column(String(64), default="")


class WeekSnapshot(Base):
    """Последняя известная версия недели группы — кэш и база для поиска изменений (п. 9)."""

    __tablename__ = "week_snapshots"

    group_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monday: Mapped[date] = mapped_column(Date, primary_key=True)
    number: Mapped[int | None] = mapped_column(Integer)
    parity: Mapped[str | None] = mapped_column(String(16))
    lessons: Mapped[list] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Минимальный журнал событий без персональных данных (например, удаление аккаунта)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event: Mapped[str] = mapped_column(String(32))
    tg_id: Mapped[int] = mapped_column(BigInteger)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Teacher(Base):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(128), unique=True)
    short_name: Mapped[str] = mapped_column(String(64))


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (UniqueConstraint("room", "building"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room: Mapped[str] = mapped_column(String(64))
    building: Mapped[str] = mapped_column(String(32), default="")


class IndexEntry(Base):
    """Плоский индекс занятий всех групп: по нему строятся расписания преподавателей и аудиторий.

    Одна строка — одно занятие одной группы с одним преподавателем (teacher_id может быть NULL).
    Перезаписывается целиком для пары (группа, неделя) при каждом обновлении недели.
    """

    __tablename__ = "lesson_index"
    __table_args__ = (
        Index("ix_index_teacher_day", "teacher_id", "day"),
        Index("ix_index_room_day", "room_id", "day"),
        Index("ix_index_group_week", "group_id", "monday"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(Integer)
    monday: Mapped[date] = mapped_column(Date)
    day: Mapped[date] = mapped_column(Date)
    pair: Mapped[str] = mapped_column(String(8))
    start: Mapped[str] = mapped_column(String(5))
    end: Mapped[str] = mapped_column(String(5))
    subject: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(64))
    teacher_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("teachers.id"))
    room_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("rooms.id"))
