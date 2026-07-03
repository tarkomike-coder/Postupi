from sqlalchemy import Boolean, Column, Integer, String

from database.db import Base


class TrackedApplicant(Base):
    """Абитуриент, за которым следим (пока один - Варя, но не хардкодим)."""

    __tablename__ = "tracked_applicants"

    id = Column(Integer, primary_key=True, index=True)
    unique_code = Column(String(20), nullable=False, unique=True, index=True)
    display_name = Column(String(200), nullable=False)
    active = Column(Boolean, nullable=False, default=True)
