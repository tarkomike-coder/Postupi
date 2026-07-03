from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from database.db import Base


class ApplicantChangeEvent(Base):
    """Человеко-читаемый лог изменений отслеживаемого абитуриента:
    смена приоритета направления, добавление/удаление направления."""

    __tablename__ = "applicant_change_events"

    id = Column(Integer, primary_key=True, index=True)
    tracked_applicant_id = Column(Integer, ForeignKey("tracked_applicants.id"), nullable=False, index=True)
    run_id = Column(Integer, ForeignKey("monitor_runs.id"), nullable=False, index=True)
    direction_id = Column(Integer, ForeignKey("directions.id"), nullable=False, index=True)

    event_type = Column(String(30), nullable=False)  # priority_changed/direction_added/direction_removed
    old_value = Column(String(50), nullable=True)
    new_value = Column(String(50), nullable=True)

    detected_at = Column(DateTime, server_default=func.now(), nullable=False)
