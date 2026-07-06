"""Полный прогон для источника МАИ на Госуслугах."""
from datetime import datetime

from config import DEFAULT_TARGET_CODE, DEFAULT_TARGET_NAME, MAI_GOSUSLUGI_UNIVERSITY, SIM_CATEGORY
from database.db import SessionLocal
from models import Direction, SeatPlan, CompetitorSnapshot, MonitorRun, TrackedApplicant, ApplicantChangeEvent
from services.mai_gosuslugi_scraper import scrape_scope, ScrapeError
from services.monte_carlo import compute_simulation


def _ensure_default_tracked_applicant(db):
    if db.query(TrackedApplicant).count() == 0:
        db.add(TrackedApplicant(unique_code=DEFAULT_TARGET_CODE, display_name=DEFAULT_TARGET_NAME, active=True))
        db.commit()


def _get_or_create_direction(db, name: str, fgos_code) -> Direction:
    direction = db.query(Direction).filter(
        Direction.name == name, Direction.university == MAI_GOSUSLUGI_UNIVERSITY,
    ).first()
    if direction is None:
        direction = Direction(name=name, university=MAI_GOSUSLUGI_UNIVERSITY, fgos_code=fgos_code)
        db.add(direction)
        db.flush()
    elif fgos_code and direction.fgos_code != fgos_code:
        direction.fgos_code = fgos_code
    return direction


def _sync_seats(db, run: MonitorRun, direction: Direction, seats):
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


def _save_snapshots(db, run: MonitorRun, direction: Direction, rows) -> int:
    snapshot_rows = [
        CompetitorSnapshot(
            run_id=run.id, direction_id=direction.id, unique_code=row.unique_code,
            category=SIM_CATEGORY, position=row.position, total_score=row.total_score,
            priority=row.priority, consent=row.consent,
        )
        for row in rows
    ]
    db.bulk_save_objects(snapshot_rows)
    return len(snapshot_rows)


def _log_change_events(db, run: MonitorRun):
    applicants = db.query(TrackedApplicant).filter(TrackedApplicant.active.is_(True)).all()
    for applicant in applicants:
        previous_run_id = (
            db.query(CompetitorSnapshot.run_id)
            .join(Direction, Direction.id == CompetitorSnapshot.direction_id)
            .filter(
                CompetitorSnapshot.run_id != run.id,
                CompetitorSnapshot.unique_code == applicant.unique_code,
                CompetitorSnapshot.category == SIM_CATEGORY,
                Direction.university == MAI_GOSUSLUGI_UNIVERSITY,
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
                Direction.university == MAI_GOSUSLUGI_UNIVERSITY,
            ).all()
        )
        current = {r.direction_id: r.priority for r in current_rows}

        previous = {}
        if previous_run_id:
            previous_rows = (
                db.query(CompetitorSnapshot)
                .filter(
                    CompetitorSnapshot.run_id == previous_run_id,
                    CompetitorSnapshot.unique_code == applicant.unique_code,
                    CompetitorSnapshot.category == SIM_CATEGORY,
                ).all()
            )
            previous = {r.direction_id: r.priority for r in previous_rows}

        for direction_id, priority in current.items():
            if direction_id not in previous:
                db.add(ApplicantChangeEvent(
                    tracked_applicant_id=applicant.id, run_id=run.id, direction_id=direction_id,
                    event_type="direction_added", old_value=None, new_value=str(priority),
                ))
            elif previous[direction_id] != priority:
                db.add(ApplicantChangeEvent(
                    tracked_applicant_id=applicant.id, run_id=run.id, direction_id=direction_id,
                    event_type="priority_changed",
                    old_value=str(previous[direction_id]), new_value=str(priority),
                ))
        for direction_id, priority in previous.items():
            if direction_id not in current:
                db.add(ApplicantChangeEvent(
                    tracked_applicant_id=applicant.id, run_id=run.id, direction_id=direction_id,
                    event_type="direction_removed", old_value=str(priority), new_value=None,
                ))


def run_mai_gosuslugi_sync(trigger: str = "schedule") -> MonitorRun:
    db = SessionLocal()
    run = MonitorRun(status="running", trigger=trigger, university=MAI_GOSUSLUGI_UNIVERSITY)
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        _ensure_default_tracked_applicant(db)

        directions = scrape_scope()
        run.directions_scraped = len(directions)

        for d in directions:
            direction = _get_or_create_direction(db, d.name, d.fgos_code)
            db.flush()
            _sync_seats(db, run, direction, d.seats)
            _save_snapshots(db, run, direction, d.rows)
        db.commit()

        _log_change_events(db, run)
        db.commit()

        compute_simulation(db, run.id)

        run.status = "ok"
    except ScrapeError as e:
        run.status = "error"
        run.error_message = str(e)[:2000]
    except Exception as e:
        run.status = "error"
        run.error_message = f"{type(e).__name__}: {e}"[:2000]
    finally:
        run.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
        db.expunge(run)
        db.close()

    return run
