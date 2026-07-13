from sqlalchemy import inspect, text

from database.db import Base, engine
import models  # noqa: F401  (регистрирует все модели в Base.metadata)


def ensure_schema():
    Base.metadata.create_all(bind=engine)
    _ensure_column("directions", "external_group_id", "INTEGER")
    _ensure_column("monitor_runs", "model_version", "VARCHAR(50)")
    _ensure_column("monitor_runs", "coverage", "VARCHAR(50)")
    _ensure_column("simulation_results", "application_deadline_at", "TIMESTAMP WITH TIME ZONE")
    _ensure_column("simulation_results", "time_left_ratio", "FLOAT")
    _ensure_column("simulation_results", "new_applicant_risk_factor", "FLOAT")
    _ensure_column("simulation_results", "expected_new_applicants", "FLOAT")
    _ensure_index("ix_directions_external_group_id", "directions", "external_group_id")


def _ensure_column(table_name: str, column_name: str, ddl_type: str) -> None:
    columns = {column["name"] for column in inspect(engine).get_columns(table_name)}
    if column_name in columns:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl_type}"))


def _ensure_index(index_name: str, table_name: str, column_name: str) -> None:
    indexes = {index["name"] for index in inspect(engine).get_indexes(table_name)}
    if index_name in indexes:
        return
    with engine.begin() as conn:
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column_name})"))
