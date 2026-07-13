from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from database.db import Base


class MonitorRun(Base):
    __tablename__ = "monitor_runs"

    id = Column(Integer, primary_key=True, index=True)
    university = Column(String(50), nullable=False, default="МАИ", index=True)
    started_at = Column(DateTime, server_default=func.now(), nullable=False)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="running")  # running/ok/partial/error
    trigger = Column(String(20), nullable=False, default="schedule")  # schedule/manual/manual_import
    source_generation_token = Column(String(100), nullable=True)
    model_version = Column(String(50), nullable=True)
    coverage = Column(String(50), nullable=True)
    directions_scraped = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
