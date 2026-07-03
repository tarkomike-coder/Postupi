"""Однократный прогон - для ручного запуска (python -m workers.run_monitor)
и для планировщика/кнопки "обновить" (services.sync.run_full_sync)."""
from services.sync import run_full_sync


def run(trigger: str = "manual"):
    result = run_full_sync(trigger=trigger)
    print(f"RUN {result.id}: status={result.status} directions={result.directions_scraped} "
          f"error={result.error_message}")
    return result


if __name__ == "__main__":
    run()
