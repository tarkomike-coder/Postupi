from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.db import SessionLocal
from models import (
    MonitorRun, Direction, CompetitorSnapshot, SeatPlan,
    TrackedApplicant, SimulationResult, ApplicantChangeEvent,
)
from services.sync import run_full_sync
from services.bauman_import import run_bauman_sync
from services.mai_gosuslugi_import import run_mai_gosuslugi_sync
from services.full_snapshot_import import run_bauman_full_snapshot_sync, run_mai_full_snapshot_sync
from config import FULL_SNAPSHOT_DATABASE_URL, SIM_CATEGORY

router = APIRouter(prefix="/postupi", tags=["postupi"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _latest_ok_run(db: Session, university: str) -> MonitorRun:
    run = (
        db.query(MonitorRun)
        .filter(MonitorRun.status == "ok", MonitorRun.university == university)
        .order_by(MonitorRun.id.desc())
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail=f"Ещё нет ни одного успешного прогона для {university}")
    return run


def _latest_seats(db: Session, direction_id: int):
    return (
        db.query(SeatPlan)
        .filter(SeatPlan.direction_id == direction_id)
        .order_by(SeatPlan.valid_from.desc())
        .first()
    )


def build_status(db: Session, university: str) -> dict:
    run = _latest_ok_run(db, university)
    applicant = db.query(TrackedApplicant).filter(TrackedApplicant.active.is_(True)).first()
    if not applicant:
        raise HTTPException(status_code=404, detail="Нет отслеживаемого абитуриента")

    rows = (
        db.query(CompetitorSnapshot)
        .filter(
            CompetitorSnapshot.run_id == run.id,
            CompetitorSnapshot.unique_code == applicant.unique_code,
            CompetitorSnapshot.category == SIM_CATEGORY,
        )
        .all()
    )
    sim_by_direction = {
        r.direction_id: r
        for r in db.query(SimulationResult).filter(
            SimulationResult.run_id == run.id,
            SimulationResult.tracked_applicant_id == applicant.id,
        )
    }

    directions = []
    for row in sorted(rows, key=lambda r: r.priority or 999):
        direction = db.get(Direction, row.direction_id)
        seats = _latest_seats(db, direction.id)
        sim = sim_by_direction.get(direction.id)
        directions.append({
            "direction_id": direction.id,
            "external_group_id": direction.external_group_id,
            "name": direction.name,
            "fgos_code": direction.fgos_code,
            "cutoff_2025": direction.cutoff_2025,
            "priority": row.priority,
            "position": row.position,
            "total_score": row.total_score,
            "consent": row.consent,
            "seats_budget": seats.seats_budget if seats else None,
            "predicted_cutoff_score": sim.predicted_cutoff_score if sim else None,
            "predicted_gap": sim.predicted_gap if sim else None,
            "application_deadline_at": sim.application_deadline_at if sim else None,
            "time_left_ratio": sim.time_left_ratio if sim else None,
            "new_applicant_risk_factor": sim.new_applicant_risk_factor if sim else None,
            "expected_new_applicants": sim.expected_new_applicants if sim else None,
            "deterministic_admitted": sim.deterministic_admitted if sim else None,
            "probability_pct": sim.probability_pct if sim else None,
            "standalone_probability_pct": sim.standalone_probability_pct if sim else None,
            "real_competitor_count": sim.real_competitor_count if sim else None,
            "real_competitor_position": sim.real_competitor_position if sim else None,
            "avg_real_competitor_score": sim.avg_real_competitor_score if sim else None,
            "gap_to_avg": sim.gap_to_avg if sim else None,
            "min_real_competitor_score": sim.min_real_competitor_score if sim else None,
            "gap_to_min": sim.gap_to_min if sim else None,
            "cascaded_in_count": sim.cascaded_in_count if sim else None,
            "consent_elsewhere_count": sim.consent_elsewhere_count if sim else None,
            "no_consent_count": sim.no_consent_count if sim else None,
        })

    return {
        "university": university,
        "run": {
            "id": run.id,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "trigger": run.trigger,
            "source_generation_token": run.source_generation_token,
            "model_version": run.model_version,
            "coverage": run.coverage,
        },
        "directions": directions,
    }


def build_history(db: Session, university: str) -> dict:
    applicant = db.query(TrackedApplicant).filter(TrackedApplicant.active.is_(True)).first()
    if not applicant:
        raise HTTPException(status_code=404, detail="Нет отслеживаемого абитуриента")

    ok_runs = (
        db.query(MonitorRun)
        .filter(MonitorRun.status == "ok", MonitorRun.university == university)
        .order_by(MonitorRun.id.asc())
        .all()
    )
    run_ids = [r.id for r in ok_runs]
    run_time_by_id = {r.id: r.started_at for r in ok_runs}
    run_model_by_id = {r.id: r.model_version for r in ok_runs}
    run_coverage_by_id = {r.id: r.coverage for r in ok_runs}

    snapshots = (
        db.query(CompetitorSnapshot)
        .filter(
            CompetitorSnapshot.run_id.in_(run_ids),
            CompetitorSnapshot.unique_code == applicant.unique_code,
            CompetitorSnapshot.category == SIM_CATEGORY,
        )
        .all()
    )
    sims = (
        db.query(SimulationResult)
        .filter(SimulationResult.run_id.in_(run_ids), SimulationResult.tracked_applicant_id == applicant.id)
        .all()
    )
    sims_by_key = {(s.run_id, s.direction_id): s for s in sims}

    direction_ids = {s.direction_id for s in snapshots}
    directions_by_id = {d.id: d for d in db.query(Direction).filter(Direction.id.in_(direction_ids))}

    series = {d_id: {"direction_id": d_id, "name": directions_by_id[d_id].name,
                      "cutoff_2025": directions_by_id[d_id].cutoff_2025, "points": []}
              for d_id in direction_ids}

    for snap in sorted(snapshots, key=lambda s: s.run_id):
        sim = sims_by_key.get((snap.run_id, snap.direction_id))
        series[snap.direction_id]["points"].append({
            "run_id": snap.run_id,
            "timestamp": run_time_by_id.get(snap.run_id),
            "model_version": run_model_by_id.get(snap.run_id),
            "coverage": run_coverage_by_id.get(snap.run_id),
            "position": snap.position,
            "total_score": snap.total_score,
            "priority": snap.priority,
            "predicted_cutoff_score": sim.predicted_cutoff_score if sim else None,
            "predicted_gap": sim.predicted_gap if sim else None,
            "application_deadline_at": sim.application_deadline_at if sim else None,
            "time_left_ratio": sim.time_left_ratio if sim else None,
            "new_applicant_risk_factor": sim.new_applicant_risk_factor if sim else None,
            "expected_new_applicants": sim.expected_new_applicants if sim else None,
            "probability_pct": sim.probability_pct if sim else None,
            "standalone_probability_pct": sim.standalone_probability_pct if sim else None,
            "real_competitor_position": sim.real_competitor_position if sim else None,
            "real_competitor_count": sim.real_competitor_count if sim else None,
            "avg_real_competitor_score": sim.avg_real_competitor_score if sim else None,
            "min_real_competitor_score": sim.min_real_competitor_score if sim else None,
        })

    return {"directions": list(series.values())}


def build_events(db: Session, university: str) -> dict:
    applicant = db.query(TrackedApplicant).filter(TrackedApplicant.active.is_(True)).first()
    if not applicant:
        raise HTTPException(status_code=404, detail="Нет отслеживаемого абитуриента")

    rows = (
        db.query(ApplicantChangeEvent)
        .join(Direction, Direction.id == ApplicantChangeEvent.direction_id)
        .filter(ApplicantChangeEvent.tracked_applicant_id == applicant.id, Direction.university == university)
        .order_by(ApplicantChangeEvent.id.desc())
        .limit(200)
        .all()
    )
    directions_by_id = {d.id: d.name for d in db.query(Direction)}

    return {
        "events": [
            {
                "direction": directions_by_id.get(r.direction_id, "?"),
                "event_type": r.event_type,
                "old_value": r.old_value,
                "new_value": r.new_value,
                "detected_at": r.detected_at,
            }
            for r in rows
        ]
    }


@router.post("/refresh")
def refresh(university: str = "МАИ"):
    if university == "Бауманка":
        run = (
            run_bauman_full_snapshot_sync(trigger="manual")
            if FULL_SNAPSHOT_DATABASE_URL
            else run_bauman_sync(trigger="manual")
        )
    elif university == "МАИ Госуслуги":
        run = (
            run_mai_full_snapshot_sync(trigger="manual")
            if FULL_SNAPSHOT_DATABASE_URL
            else run_mai_gosuslugi_sync(trigger="manual")
        )
    else:
        run = run_full_sync(trigger="manual")
    # После ручного синка пересобираем статическую страницу.
    from services.snapshot import regenerate_safe
    regenerate_safe()
    return {
        "id": run.id,
        "status": run.status,
        "error_message": run.error_message,
        "directions_scraped": run.directions_scraped,
        "finished_at": run.finished_at,
    }


def list_universities(db: Session) -> dict:
    """Список вузов, по которым уже есть хотя бы один успешный прогон -
    фронтенд использует это, чтобы понять, показывать ли вкладку Бауманки."""
    rows = db.query(MonitorRun.university).filter(MonitorRun.status == "ok").distinct().all()
    return {"universities": sorted({r[0] for r in rows})}


@router.get("/status")
def status(university: str = "МАИ", db: Session = Depends(get_db)):
    return build_status(db, university)


@router.get("/history")
def history(university: str = "МАИ", db: Session = Depends(get_db)):
    return build_history(db, university)


@router.get("/events")
def events(university: str = "МАИ", db: Session = Depends(get_db)):
    return build_events(db, university)


@router.get("/universities")
def universities(db: Session = Depends(get_db)):
    return list_universities(db)
