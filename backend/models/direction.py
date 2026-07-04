from sqlalchemy import Column, Integer, String, UniqueConstraint

from database.db import Base


class Direction(Base):
    """Справочник направлений подготовки. university различает вузы (МАИ,
    Бауманка) - у Бауманки направления с тем же названием/кодом могут быть
    отдельными "конкурсными группами" (разные кафедры/профили), поэтому
    уникальность - по паре (university, name), не по одному name."""

    __tablename__ = "directions"
    __table_args__ = (UniqueConstraint("university", "name", name="uq_direction_university_name"),)

    id = Column(Integer, primary_key=True, index=True)
    university = Column(String(50), nullable=False, default="МАИ", index=True)
    name = Column(String(300), nullable=False, index=True)
    fgos_code = Column(String(20), nullable=True)
    cutoff_2025 = Column(Integer, nullable=True)  # проходной балл прошлого года (справочно)
