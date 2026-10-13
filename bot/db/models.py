from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, func
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
