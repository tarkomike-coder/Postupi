r"""Import full MAI/Bauman snapshots from the public-search project.

The old Postupi importers scrape only the directions that are interesting for
the tracked applicant. That is good enough for cards, but not for a real
cascade: deferred acceptance must see the whole university universe. This
service reads the already-normalized full snapshots from C:\Projects\mai /
the production `mai` database and feeds the existing Postupi simulation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import create_engine, text

from config import (
    DEFAULT_TARGET_CODE,
    DEFAULT_TARGET_NAME,
    FULL_COVERAGE,
    FULL_MODEL_VERSION,
    FULL_SNAPSHOT_DATABASE_URL,
    MAI_GOSUSLUGI_UNIVERSITY,
    SIM_CATEGORY,
)
from database.db import SessionLocal
from models import ApplicantChangeEvent, CompetitorSnapshot, Direction, MonitorRun, SeatPlan, TrackedApplicant
from services.monte_carlo import compute_simulation

BAUMAN_UNIVERSITY = "Бауманка"


class FullSnapshotImportError(RuntimeError):
    pass


@dataclass(frozen=True)
class SnapshotSpec:
    university: str
    snapshots_table: str
    groups_table: str
    rows_table: str


SPECS = {
    "mai": SnapshotSpec(
        university=MAI_GOSUSLUGI_UNIVERSITY,
        snapshots_table="mai_snapshots",
        groups_table="mai_competition_groups",
        rows_table="mai_applicant_rows",
    ),
    "bauman": SnapshotSpec(
        university=BAUMAN_UNIVERSITY,
        snapshots_table="bauman_snapshots",
        groups_table="bauman_competition_groups",
        rows_table="bauman_applicant_rows",
    ),
}


def _connect_args(database_url: str) -> dict:
    return {"check_same_thread": False} if database_url.startswith("sqlite") else {}


def _source_engine():
    if not FULL_SNAPSHOT_DATABASE_URL:
        raise FullSnapshotImportError(
            "FULL_SNAPSHOT_DATABASE_URL is not configured and could not be derived from DATABASE_URL"
        )
    return create_engine(FULL_SNAPSHOT_DATABASE_URL, connect_args=_connect_args(FULL_SNAPSHOT_DATABASE_URL))


def _ensure_default_tracked_applicant(db):
    if db.query(TrackedApplicant).count() == 0:
        db.add(TrackedApplicant(unique_code=DEFAULT_TARGET_CODE, display_name=DEFAULT_TARGET_NAME, active=True))
        db.commit()


def _get_or_create_direction(db, *, university: str, external_group_id: int, name: str, fgos_code: str | None):
    direction = (
        db.query(Direction)
        .filter(Direction.university == university, Direction.external_group_id == external_group_id)
        .first()
    )
    if direction is None:
        by_name = db.query(Direction).filter(Direction.university == university, Direction.name == name).first()
        if by_name is None:
            direction = Direction(
                university=university,
                external_group_id=external_group_id,
                name=name,
                fgos_code=fgos_code,
            )
            db.add(direction)
            db.flush()
        elif by_name.external_group_id in (None, external_group_id):
            direction = by_name
            direction.external_group_id = external_group_id
        else:
            direction = Direction(
                university=university,
                external_group_id=external_group_id,
                name=f"{name} ({external_group_id})",
                fgos_code=fgos_code,
            )
            db.add(direction)
            db.flush()

    same_name_taken = (
        db.query(Direction)
        .filter(Direction.university == university, Direction.name == name, Direction.id != direction.id)
        .first()
    )
    if same_name_taken is None:
        direction.name = name
    if fgos_code:
        direction.fgos_code = fgos_code
    return direction


def _sync_seats(db, run: MonitorRun, direction: Direction, seats: int | None):
    if seats is None:
        return
    latest = (
        db.query(SeatPlan)
        .filter(SeatPlan.direction_id == direction.id)
        .order_by(SeatPlan.valid_from.desc())
        .first()
    )
    if latest is None or latest.seats_budget != seats:
        db.add(SeatPlan(direction_id=direction.id, seats_budget=seats, source_run_id=run.id))


def _log_change_events(db, run: MonitorRun, university: str):
    applicants = db.query(TrackedApplicant).filter(TrackedApplicant.active.is_(True)).all()
    for applicant in applicants:
        previous_run_id = (
            db.query(CompetitorSnapshot.run_id)
            .join(Direction, Direction.id == CompetitorSnapshot.direction_id)
            .filter(
                CompetitorSnapshot.run_id != run.id,
                CompetitorSnapshot.unique_code == applicant.unique_code,
                CompetitorSnapshot.category == SIM_CATEGORY,
                Direction.university == university,
            )
            .order_by(CompetitorSnapshot.run_id.desc())
            .limit(1)
            .scalar()
        )
        current_rows = (
            db.query(CompetitorSnapshot)
            .join(Direction, Direction.id == CompetitorSnapshot.direction_id)
            .filter(
                CompetitorSnapshot.run_id == run.id,
                CompetitorSnapshot.unique_code == applicant.unique_code,
                CompetitorSnapshot.category == SIM_CATEGORY,
                Direction.university == university,
            )
            .all()
        )
        current = {r.direction_id: r.priority for r in current_rows}

        previous = {}
        if previous_run_id:
            previous_rows = (
                db.query(CompetitorSnapshot)
                .join(Direction, Direction.id == CompetitorSnapshot.direction_id)
                .filter(
                    CompetitorSnapshot.run_id == previous_run_id,
                    CompetitorSnapshot.unique_code == applicant.unique_code,
                    CompetitorSnapshot.category == SIM_CATEGORY,
                    Direction.university == university,
                )
                .all()
            )
            previous = {r.direction_id: r.priority for r in previous_rows}

        for direction_id, priority in current.items():
            if direction_id not in previous:
                db.add(
                    ApplicantChangeEvent(
                        tracked_applicant_id=applicant.id,
                        run_id=run.id,
                        direction_id=direction_id,
                        event_type="direction_added",
                        old_value=None,
                        new_value=str(priority),
                    )
                )
            elif previous[direction_id] != priority:
                db.add(
                    ApplicantChangeEvent(
                        tracked_applicant_id=applicant.id,
                        run_id=run.id,
                        direction_id=direction_id,
                        event_type="priority_changed",
                        old_value=str(previous[direction_id]),
                        new_value=str(priority),
                    )
                )
        for direction_id, priority in previous.items():
            if direction_id not in current:
                db.add(
                    ApplicantChangeEvent(
                        tracked_applicant_id=applicant.id,
                        run_id=run.id,
                        direction_id=direction_id,
                        event_type="direction_removed",
                        old_value=str(priority),
                        new_value=None,
                    )
                )


def _read_source_snapshot(source_conn, spec: SnapshotSpec) -> tuple[dict, list[dict], list[dict]]:
    snapshot = (
        source_conn.execute(
            text(
                f"""
                select id, started_at, finished_at, groups_count, rows_count, unique_applications_count
                from {spec.snapshots_table}
                where status = 'ok'
                order by finished_at desc nulls last, id desc
                limit 1
                """
            )
        )
        .mappings()
        .first()
    )
    if snapshot is None:
        raise FullSnapshotImportError(f"No ok snapshot found in {spec.snapshots_table}")

    groups = (
        source_conn.execute(
            text(
                f"""
                select id, group_id, okso_code, name, seats
                from {spec.groups_table}
                order by id
                """
            )
        )
        .mappings()
        .all()
    )
    rows = (
        source_conn.execute(
            text(
                f"""
                select application_id, group_id, position, score, priority, consent
                from {spec.rows_table}
                where snapshot_id = :snapshot_id
                """
            ),
            {"snapshot_id": snapshot["id"]},
        )
        .mappings()
        .all()
    )
    return dict(snapshot), [dict(row) for row in groups], [dict(row) for row in rows]


def run_full_snapshot_sync(kind: str, trigger: str = "schedule") -> MonitorRun:
    spec = SPECS[kind]
    db = SessionLocal()
    run = MonitorRun(
        status="running",
        trigger=trigger,
        university=spec.university,
        model_version=FULL_MODEL_VERSION,
        coverage=FULL_COVERAGE,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        _ensure_default_tracked_applicant(db)
        source_engine = _source_engine()
        try:
            with source_engine.connect() as source_conn:
                snapshot, groups, rows = _read_source_snapshot(source_conn, spec)
        finally:
            source_engine.dispose()

        run.source_generation_token = f"{kind}:snapshot:{snapshot['id']}"
        run.directions_scraped = len(groups)

        direction_by_source_group_id = {}
        for group in groups:
            direction = _get_or_create_direction(
                db,
                university=spec.university,
                external_group_id=int(group["group_id"]),
                name=group["name"],
                fgos_code=group["okso_code"],
            )
            _sync_seats(db, run, direction, group["seats"])
            direction_by_source_group_id[group["id"]] = direction

        snapshot_rows = []
        for row in rows:
            direction = direction_by_source_group_id.get(row["group_id"])
            if direction is None:
                continue
            snapshot_rows.append(
                CompetitorSnapshot(
                    run_id=run.id,
                    direction_id=direction.id,
                    unique_code=str(row["application_id"]),
                    category=SIM_CATEGORY,
                    position=row["position"],
                    total_score=row["score"],
                    priority=row["priority"],
                    consent=bool(row["consent"]),
                )
            )
        db.bulk_save_objects(snapshot_rows)
        db.commit()

        _log_change_events(db, run, spec.university)
        db.commit()

        compute_simulation(db, run.id)
        run.status = "ok"
    except Exception as exc:  # noqa: BLE001
        run.status = "error"
        run.error_message = f"{type(exc).__name__}: {exc}"[:2000]
    finally:
        run.finished_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
        db.refresh(run)
        db.expunge(run)
        db.close()

    return run


def run_mai_full_snapshot_sync(trigger: str = "schedule") -> MonitorRun:
    return run_full_snapshot_sync("mai", trigger=trigger)


def run_bauman_full_snapshot_sync(trigger: str = "schedule") -> MonitorRun:
    return run_full_snapshot_sync("bauman", trigger=trigger)
