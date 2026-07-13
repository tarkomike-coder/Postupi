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
    # (и единственным приоритетом 1)". Не зависит от того, что у неё есть
    # другие направления - всегда показывается.
    standalone_probability_pct = Column(Float, nullable=True)

    # Прогноз проходного балла - среднее по Monte Carlo прогонам (не
    # "дождись конца приёма, чтобы узнать" - оценка на основе текущих
    # данных и вероятного оттока/прихода конкурентов). Всегда доступен
    # (в отличие от "официального" балла, который считается только когда
    # места буквально заполнены согласившимися).
    predicted_cutoff_score = Column(Float, nullable=True)
    predicted_gap = Column(Float, nullable=True)

    application_deadline_at = Column(DateTime(timezone=True), nullable=True)
    time_left_ratio = Column(Float, nullable=True)
    new_applicant_risk_factor = Column(Float, nullable=True)
    expected_new_applicants = Column(Float, nullable=True)

    # "Реальные" конкуренты - те, кого алгоритм отложенного принятия
    # (по ТЕКУЩИМ согласиям, без рандомизации) реально распределяет именно
    # сюда: то есть люди, которые либо указали это направление приоритетом
    # 1, либо не проходят на свои более высокие приоритеты и каскадом
    # попадают сюда. Человек с согласием и более высоким приоритетом,
    # который туда реально проходит, сюда не считается - он не мешает.
    real_competitor_count = Column(Integer, nullable=True)
    real_competitor_position = Column(Integer, nullable=True)
    avg_real_competitor_score = Column(Float, nullable=True)
    gap_to_avg = Column(Float, nullable=True)
    min_real_competitor_score = Column(Integer, nullable=True)
    gap_to_min = Column(Integer, nullable=True)

    # Разбивка конкурентов по группам (для отдельного графика "состав
    # конкуренции"):
    cascaded_in_count = Column(Integer, nullable=True)     # = real_competitor_count
    consent_elsewhere_count = Column(Integer, nullable=True)  # согласие есть, но каскад уводит в другое место
    no_consent_count = Column(Integer, nullable=True)      # согласия ещё нет вообще

    trials = Column(Integer, nullable=True)

    computed_at = Column(DateTime, server_default=func.now(), nullable=False)
