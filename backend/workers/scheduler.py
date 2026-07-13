"""Фоновый планировщик - 2 прогона в день (см. SCHEDULE_TIMES_MSK), плюс
ручной запуск доступен отдельно через POST /postupi/refresh."""
from datetime import datetime
from zoneinfo import ZoneInfo

from config import SCHEDULE_TIMES_MSK
from database.db import SessionLocal
from models import MonitorRun
from workers.run_monitor import run_all

_scheduler = None
_MSK = ZoneInfo("Europe/Moscow")


def _run_scheduled():
    run_all(trigger="schedule")


def _parse_schedule_time(now: datetime, time_str: str) -> datetime:
    hour, minute = time_str.split(":")
    return now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)


def needs_startup_catchup(
    *,
    now: datetime,
    last_ok_started_at: datetime | None,
    schedule_times: list[str],
) -> bool:
    due_slots = [_parse_schedule_time(now, t) for t in schedule_times]
    due_slots = [slot for slot in due_slots if slot <= now]
    if not due_slots:
        return False
    if last_ok_started_at is None:
        return True
    return last_ok_started_at < max(due_slots)


def _oldest_latest_ok_started_at():
    db = SessionLocal()
    try:
        latest_by_university = (
            db.query(MonitorRun.university, MonitorRun.started_at)
            .filter(MonitorRun.status == "ok")
            .order_by(MonitorRun.university.asc(), MonitorRun.started_at.desc())
            .all()
        )
    finally:
        db.close()

    latest = {}
    for university, started_at in latest_by_university:
        latest.setdefault(university, started_at)
    return min(latest.values()) if latest else None


def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.date import DateTrigger

    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone="Europe/Moscow")
    for time_str in SCHEDULE_TIMES_MSK:
        hour, minute = time_str.split(":")
        scheduler.add_job(_run_scheduled, CronTrigger(hour=int(hour), minute=int(minute)))
    scheduler.start()
    if needs_startup_catchup(
        now=datetime.now(_MSK).replace(tzinfo=None),
        last_ok_started_at=_oldest_latest_ok_started_at(),
        schedule_times=SCHEDULE_TIMES_MSK,
    ):
        scheduler.add_job(
            _run_scheduled,
            DateTrigger(run_date=datetime.now(_MSK)),
            id="startup-catchup",
            replace_existing=True,
        )
    _scheduler = scheduler
    return scheduler
