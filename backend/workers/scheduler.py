"""Фоновый планировщик - 2 прогона в день (см. SCHEDULE_TIMES_MSK), плюс
ручной запуск доступен отдельно через POST /postupi/refresh."""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import SCHEDULE_TIMES_MSK
from workers.run_monitor import run

_scheduler = None


def _run_scheduled():
    run(trigger="schedule")


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone="Europe/Moscow")
    for time_str in SCHEDULE_TIMES_MSK:
        hour, minute = time_str.split(":")
        scheduler.add_job(_run_scheduled, CronTrigger(hour=int(hour), minute=int(minute)))
    scheduler.start()
    _scheduler = scheduler
    return scheduler
