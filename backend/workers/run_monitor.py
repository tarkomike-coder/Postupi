"""Однократный прогон - для ручного запуска (python -m workers.run_monitor)
и для планировщика/кнопки "обновить" (services.sync.run_full_sync,
services.bauman_import.run_bauman_sync)."""
from services.sync import run_full_sync
from services.bauman_import import run_bauman_sync
from services.mai_gosuslugi_import import run_mai_gosuslugi_sync


def run(trigger: str = "manual"):
    result = run_full_sync(trigger=trigger)
    print(f"RUN {result.id} (МАИ): status={result.status} directions={result.directions_scraped} "
          f"error={result.error_message}")
    return result


def run_bauman(trigger: str = "manual"):
    result = run_bauman_sync(trigger=trigger)
    print(f"RUN {result.id} (Бауманка): status={result.status} directions={result.directions_scraped} "
          f"error={result.error_message}")
    return result


def run_mai_gosuslugi(trigger: str = "manual"):
    result = run_mai_gosuslugi_sync(trigger=trigger)
    print(f"RUN {result.id} (МАИ Госуслуги): status={result.status} directions={result.directions_scraped} "
          f"error={result.error_message}")
    return result


def run_all(trigger: str = "manual"):
    results = run(trigger=trigger), run_bauman(trigger=trigger), run_mai_gosuslugi(trigger=trigger)
    # После синка пересобираем статическую страницу с вшитыми данными.
    from services.snapshot import regenerate_safe
    regenerate_safe()
    return results


if __name__ == "__main__":
    run_all()
