from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.sql import func

from database.db import Base


class CompetitorSnapshot(Base):
    """Одна строка = один абитуриент в списке одного направления на момент
    прогона. Полный срез каждый раз (не только диффы) - дёшево по месту,
    зато можно пересчитать симуляцию задним числом.

    category сохраняется как есть (БВИ / особая квота / целевая квота /
    общий конкурс) - на странице всё равно приходит бесплатно вместе с
    общим конкурсом, фильтрация под текущий scope (SIM_CATEGORY) происходит
    в запросах, а не при скрейпинге."""

    __tablename__ = "competitor_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("monitor_runs.id"), nullable=False, index=True)
    direction_id = Column(Integer, ForeignKey("directions.id"), nullable=False, index=True)

    unique_code = Column(String(20), nullable=False, index=True)
    category = Column(String(200), nullable=False)
    position = Column(Integer, nullable=True)
    total_score = Column(Integer, nullable=True)
    priority = Column(Integer, nullable=True)
    consent = Column(Boolean, nullable=False, default=False)
