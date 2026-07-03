from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlalchemy.sql import func

from database.db import Base


class SeatPlan(Base):
    """КЦП (бюджетные места) по направлению. Новая строка добавляется только
    если число мест реально изменилось - история сохраняется, не
    перезаписывается."""

    __tablename__ = "seat_plans"

    id = Column(Integer, primary_key=True, index=True)
    direction_id = Column(Integer, ForeignKey("directions.id"), nullable=False, index=True)
    seats_budget = Column(Integer, nullable=False)
    valid_from = Column(DateTime, server_default=func.now(), nullable=False)
    source_run_id = Column(Integer, ForeignKey("monitor_runs.id"), nullable=True)
