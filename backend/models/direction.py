from sqlalchemy import Column, Integer, String

from database.db import Base


class Direction(Base):
    """Справочник направлений подготовки (в нашем scope: МАИ, Базовое высшее
    образование, Очная, Бюджет). Код ФГОС приходит из seat_plan и может быть
    пустым, пока план приёма ещё не спарсен."""

    __tablename__ = "directions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(300), nullable=False, unique=True, index=True)
    fgos_code = Column(String(20), nullable=True)
