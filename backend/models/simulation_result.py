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

    # Итог полной симуляции (с учётом каскада ЕЁ СОБСТВЕННЫХ приоритетов):
    # куда её реально распределит алгоритм, если сейчас закрыть приём.
    deterministic_admitted = Column(Boolean, nullable=False, default=False)
    probability_pct = Column(Float, nullable=True)

    # Независимая оценка направления - "как если бы оно было единственным
    # (и единственным приоритетом 1)". Не зависит от того, что у нее есть
    # другие направления - честная оценка именно этого направления самого
    # по себе, всегда показывается (не бывает "0%, потому что пройдёт выше").
    standalone_probability_pct = Column(Float, nullable=True)

    # "Официальный" проходной балл - минимальный балл среди зачисленных,
    # ЕСЛИ направление уже заполнено полностью (иначе None - рано).
    cutoff_score_estimate = Column(Integer, nullable=True)
    gap = Column(Integer, nullable=True)  # балл абитуриента - cutoff_score_estimate

    # Статистика по факту ПОДАННЫХ согласий на это направление сейчас
    # (доступна почти всегда, даже когда мест ещё не набралось) - даёт
    # содержательную картину конкуренции без пустых "-".
    consented_count = Column(Integer, nullable=True)
    consented_position = Column(Integer, nullable=True)  # её место среди подавших согласие
    avg_competitor_score = Column(Float, nullable=True)
    gap_to_avg = Column(Float, nullable=True)
    min_competitor_score = Column(Integer, nullable=True)
    gap_to_min = Column(Integer, nullable=True)

    trials = Column(Integer, nullable=True)

    computed_at = Column(DateTime, server_default=func.now(), nullable=False)
