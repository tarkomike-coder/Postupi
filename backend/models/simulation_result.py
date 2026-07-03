from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer
from sqlalchemy.sql import func
from sqlalchemy import DateTime

from database.db import Base


class SimulationResult(Base):
    """Результат симуляции распределения (детерминированная DA) и
    Monte Carlo слоя поверх неё - для одного отслеживаемого абитуриента,
    по каждому направлению, на конкретный прогон."""

    __tablename__ = "simulation_results"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("monitor_runs.id"), nullable=False, index=True)
    tracked_applicant_id = Column(Integer, ForeignKey("tracked_applicants.id"), nullable=False, index=True)
    direction_id = Column(Integer, ForeignKey("directions.id"), nullable=False, index=True)

    deterministic_admitted = Column(Boolean, nullable=False, default=False)
    cutoff_score_estimate = Column(Integer, nullable=True)
    gap = Column(Integer, nullable=True)  # балл абитуриента - cutoff_score_estimate

    probability_pct = Column(Float, nullable=True)
    # P(зачислена именно сюда | не прошла ни на один более высокий приоритет) -
    # "запасной вариант": насколько надёжно это направление, ЕСЛИ более
    # желанные приоритеты не сработают. Для приоритета 1 совпадает с
    # probability_pct.
    conditional_probability_pct = Column(Float, nullable=True)
    trials = Column(Integer, nullable=True)

    computed_at = Column(DateTime, server_default=func.now(), nullable=False)
