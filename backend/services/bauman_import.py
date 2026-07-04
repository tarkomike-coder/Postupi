"""Импорт данных Бауманки из CSV, выгруженных с Госуслуг (Вуз-навигатор,
"Списки подавших документы" -> направление -> "Скачать в виде таблицы").

Сбор самих CSV - ручной шаг (Claude делает это по просьбе пользователя,
используя уже залогиненную в Госуслуги сессию в браузере - см. обсуждение:
сервер никогда не хранит и не использует чужую госуслуговскую сессию).
Здесь - только разбор уже готового файла и запись в БД по ТОЙ ЖЕ схеме,
что и МАИ (CompetitorSnapshot с category=SIM_CATEGORY), чтобы переиспользовать
существующую симуляцию (services/monte_carlo.py) без каких-либо изменений.
"""
import csv
import io
from datetime import datetime

from config import SIM_CATEGORY, DEFAULT_TARGET_CODE, DEFAULT_TARGET_NAME
from database.db import SessionLocal
from models import Direction, SeatPlan, CompetitorSnapshot, MonitorRun, TrackedApplicant
from services.monte_carlo import compute_simulation

UNIVERSITY = "Бауманка"


def _to_int(value):
    value = (value or "").strip()
    if not value or value in ("—", "-"):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_csv_text(csv_text: str) -> list:
    """CSV с Госуслуг: разделитель ';', UTF-8 (с BOM), поля в кавычках.
    Столбцы: Порядковый номер;ID участника;Приоритет конкурса;
    Подано согласие;Сумма баллов;Баллы за ВИ;Баллы за ИД;Статус;
    Дата выбора конкурсной группы по Москве."""
    reader = csv.DictReader(io.StringIO(csv_text), delimiter=";")
    rows = []
    for r in reader:
        priority = _to_int(r.get("Приоритет конкурса"))
        score = _to_int(r.get("Сумма баллов"))
        code = (r.get("ID участника") or "").strip()
        consent_raw = (r.get("Подано согласие") or "").strip()
        consent = bool(consent_raw) and consent_raw not in ("—", "-")
        if not code or priority is None or score is None:
            continue  # тот же принцип, что у МАИ - без балла не участник, а "рано считать"
        rows.append({
            "position": _to_int(r.get("Порядковый номер")),
            "unique_code": code,
            "priority": priority,
            "consent": consent,
            "total_score": score,
        })
    return rows


def _ensure_default_tracked_applicant(db):
    if db.query(TrackedApplicant).count() == 0:
        db.add(TrackedApplicant(unique_code=DEFAULT_TARGET_CODE, display_name=DEFAULT_TARGET_NAME, active=True))
        db.commit()


def _import_direction(db, run: MonitorRun, name: str, fgos_code: str, seats: int, csv_text: str) -> int:
    direction = db.query(Direction).filter(
        Direction.name == name, Direction.university == UNIVERSITY,
    ).first()
    if direction is None:
        direction = Direction(name=name, university=UNIVERSITY, fgos_code=fgos_code)
        db.add(direction)
        db.flush()
    elif fgos_code and direction.fgos_code != fgos_code:
        direction.fgos_code = fgos_code

    latest_seats = (
        db.query(SeatPlan)
        .filter(SeatPlan.direction_id == direction.id)
        .order_by(SeatPlan.valid_from.desc())
        .first()
    )
    if latest_seats is None or latest_seats.seats_budget != seats:
        db.add(SeatPlan(direction_id=direction.id, seats_budget=seats, source_run_id=run.id))

    rows = parse_csv_text(csv_text)
    snapshot_rows = [
        CompetitorSnapshot(
            run_id=run.id,
            direction_id=direction.id,
            unique_code=row["unique_code"],
            category=SIM_CATEGORY,
            position=row["position"],
            total_score=row["total_score"],
            priority=row["priority"],
            consent=row["consent"],
        )
        for row in rows
    ]
    db.bulk_save_objects(snapshot_rows)
    return len(snapshot_rows)


def run_bauman_import(directions_data: list) -> MonitorRun:
    """directions_data: [{"name": str, "fgos_code": str|None, "seats": int,
    "csv_text": str}, ...] - один элемент на направление."""
    db = SessionLocal()
    run = MonitorRun(status="running", trigger="manual_import", university=UNIVERSITY)
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        _ensure_default_tracked_applicant(db)

        for item in directions_data:
            _import_direction(db, run, item["name"], item.get("fgos_code"), item["seats"], item["csv_text"])
        db.commit()
        run.directions_scraped = len(directions_data)

        compute_simulation(db, run.id)

        run.status = "ok"
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
