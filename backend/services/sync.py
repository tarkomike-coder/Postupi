"""Полный цикл одного прогона: скрейпинг -> запись в БД -> детект изменений
у отслеживаемых абитуриентов -> симуляция. Вызывается и планировщиком, и
кнопкой "обновить" в API (backend/workers/run_monitor.py - тонкая обёртка
над run_full_sync)."""
import os
import re
import shutil
from datetime import datetime

from config import (
    RAW_SNAPSHOTS_DIR, RAW_SNAPSHOTS_TO_KEEP,
    DEFAULT_TARGET_CODE, DEFAULT_TARGET_NAME, SIM_CATEGORY,
)
from database.db import SessionLocal
from models import Direction, SeatPlan, CompetitorSnapshot, TrackedApplicant, ApplicantChangeEvent, MonitorRun
from services.mai_list_scraper import scrape_scope, ScrapeError
from services.seat_plan_scraper import scrape_seat_plan
from services.monte_carlo import compute_simulation


def _normalize_name(name: str) -> str:
    return name.strip().replace("ё", "е").replace("Ё", "Е")


def _get_or_create_direction(db, name: str) -> Direction:
    direction = db.query(Direction).filter(Direction.name == name).first()
    if direction is None:
        direction = Direction(name=name)
        db.add(direction)
        db.flush()
    return direction


def _ensure_default_tracked_applicant(db):
    exists = db.query(TrackedApplicant).count()
    if exists == 0:
        db.add(TrackedApplicant(unique_code=DEFAULT_TARGET_CODE, display_name=DEFAULT_TARGET_NAME, active=True))
        db.commit()


def _sync_seat_plan(db, run: MonitorRun, direction_by_name: dict):
    plan = scrape_seat_plan()
    plan_by_normalized = {_normalize_name(name): info for name, info in plan.items()}

    for name, direction in direction_by_name.items():
        info = plan.get(name) or plan_by_normalized.get(_normalize_name(name))
        if not info:
            continue  # нет данных о местах для этого направления в этом прогоне

        if direction.fgos_code != info["fgos_code"]:
            direction.fgos_code = info["fgos_code"]

        latest = (
            db.query(SeatPlan)
            .filter(SeatPlan.direction_id == direction.id)
            .order_by(SeatPlan.valid_from.desc())
            .first()
        )
        if latest is None or latest.seats_budget != info["seats"]:
            db.add(SeatPlan(direction_id=direction.id, seats_budget=info["seats"], source_run_id=run.id))


def _save_competitor_snapshots(db, run: MonitorRun, directions, direction_by_name: dict):
    rows = []
    for d in directions:
        direction = direction_by_name[d.name]
        for ct in d.category_tables:
            for row in ct.rows:
                rows.append(CompetitorSnapshot(
                    run_id=run.id,
                    direction_id=direction.id,
                    unique_code=row.unique_code,
                    category=ct.category,
                    position=row.position,
                    total_score=row.total_score,
                    priority=row.priority,
                    consent=row.consent,
                ))
    db.bulk_save_objects(rows)


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w\-.а-яА-ЯёЁ ]", "_", name)[:120]


def _save_raw_snapshots(run_id: int, directions):
    os.makedirs(RAW_SNAPSHOTS_DIR, exist_ok=True)
    run_dir = os.path.join(RAW_SNAPSHOTS_DIR, f"run_{run_id}")
    os.makedirs(run_dir, exist_ok=True)
    for d in directions:
        path = os.path.join(run_dir, f"{_safe_filename(d.name)}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(d.raw_html)

    existing_runs = sorted(
        (p for p in os.listdir(RAW_SNAPSHOTS_DIR) if p.startswith("run_")),
        key=lambda p: int(p.split("_")[1]),
    )
    for stale in existing_runs[:-RAW_SNAPSHOTS_TO_KEEP]:
        shutil.rmtree(os.path.join(RAW_SNAPSHOTS_DIR, stale), ignore_errors=True)


def _log_change_events(db, run: MonitorRun, direction_by_name: dict):
    applicants = db.query(TrackedApplicant).filter(TrackedApplicant.active.is_(True)).all()
    previous_run = (
        db.query(MonitorRun)
        .filter(MonitorRun.status == "ok", MonitorRun.id != run.id)
        .order_by(MonitorRun.id.desc())
        .first()
    )

    for applicant in applicants:
        current_rows = (
            db.query(CompetitorSnapshot)
            .filter(
                CompetitorSnapshot.run_id == run.id,
                CompetitorSnapshot.unique_code == applicant.unique_code,
                CompetitorSnapshot.category == SIM_CATEGORY,
            ).all()
        )
        current = {r.direction_id: r.priority for r in current_rows}

        previous = {}
        if previous_run:
            previous_rows = (
                db.query(CompetitorSnapshot)
                .filter(
                    CompetitorSnapshot.run_id == previous_run.id,
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


def run_full_sync(trigger: str = "schedule") -> MonitorRun:
    db = SessionLocal()
    run = MonitorRun(status="running", trigger=trigger)
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        _ensure_default_tracked_applicant(db)

        generation_token, directions = scrape_scope()
        run.source_generation_token = generation_token
        run.directions_scraped = len(directions)

        direction_by_name = {d.name: _get_or_create_direction(db, d.name) for d in directions}
        db.flush()

        _sync_seat_plan(db, run, direction_by_name)
        _save_competitor_snapshots(db, run, directions, direction_by_name)
        db.commit()

        _save_raw_snapshots(run.id, directions)

        _log_change_events(db, run, direction_by_name)
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
