"""Скрейпер конкурсных списков МГТУ им. Баумана через публичный (без
логина) JSON API портала Госуслуг ("Вуз-навигатор"):

- GET .../competition/{groupId}/applicants - сырой список поступающих по
  одной конкурсной группе (rating/priority/consent/sumMark/idApplication).
  Подтверждено curl-ом без единой cookie - это то самое "работало в Edge
  без логина", про которое говорил пользователь.
- POST .../educational-programs/items {"competitionIds": [...]} - название
  направления (oksoName/oksoCode) и число бюджетных мест (numberPlaces)
  по тем же id. Тоже без авторизации.

Список groupId (BAUMAN_GROUP_IDS в config.py) собран руками через браузер
и не выводится одним запросом - см. комментарий в конфиге. Форма вывода
специально повторяет mai_list_scraper.py (DirectionRow/CategoryTable-like
поля), чтобы дальше по пайплайну (sync/monte_carlo) всё было единообразно.
"""
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from config import (
    BAUMAN_API_BASE, BAUMAN_ITEMS_URL, BAUMAN_GROUP_IDS, BAUMAN_HTTP_HEADERS,
    REQUEST_TIMEOUT, RETRIES,
)

session = requests.Session()
session.headers.update(BAUMAN_HTTP_HEADERS)


class ScrapeError(RuntimeError):
    pass


@dataclass
class DirectionRow:
    position: Optional[int]
    unique_code: str
    total_score: Optional[int]
    priority: Optional[int]
    consent: bool


@dataclass
class DirectionResult:
    name: str
    fgos_code: Optional[str]
    seats: Optional[int]
    group_id: int
    rows: list = field(default_factory=list)


def _request_json(method: str, url: str, **kwargs):
    last_exc = None
    for attempt in range(RETRIES):
        try:
            r = session.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
            if r.status_code == 200:
                return r.json()
            last_exc = ScrapeError(f"HTTP {r.status_code} for {url}: {r.text[:300]}")
        except requests.RequestException as e:
            last_exc = e
        time.sleep(0.5 * (attempt + 1))
    raise last_exc


def _fetch_program_meta(group_ids: list) -> dict:
    """{groupId: {"name", "fgos_code", "seats"}} через educational-programs/items."""
    items = _request_json(
        "post", BAUMAN_ITEMS_URL,
        params={"page": 0, "size": max(len(group_ids), 1)},
        json={"competitionIds": group_ids},
    )
    meta = {}
    for item in items:
        okso_code = item.get("oksoCode") or ""
        if okso_code.startswith("2."):
            okso_code = okso_code[2:]
        meta[item["id"]] = {
            "name": item.get("oksoName") or okso_code or f"Направление {item['id']}",
            "fgos_code": okso_code or None,
            "seats": item.get("numberPlaces"),
        }
    return meta


def _fetch_applicants(group_id: int) -> list:
    data = _request_json("get", f"{BAUMAN_API_BASE}/competition/{group_id}/applicants")
    return data.get("applicants", [])


def _to_score(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def scrape_scope() -> list:
    """Возвращает [DirectionResult, ...] по всем group id из BAUMAN_GROUP_IDS."""
    if not BAUMAN_GROUP_IDS:
        raise ScrapeError("BAUMAN_GROUP_IDS пуст - нечего скрейпить")

    meta = _fetch_program_meta(BAUMAN_GROUP_IDS)

    directions = []
    for group_id in BAUMAN_GROUP_IDS:
        info = meta.get(group_id)
        if not info:
            raise ScrapeError(f"educational-programs/items не вернул метаданные для groupId={group_id}")

        applicants = _fetch_applicants(group_id)
        rows = []
        for a in applicants:
            code = a.get("idApplication")
            score = _to_score(a.get("sumMark"))
            if code is None or not score:
                continue  # тот же принцип, что у МАИ - нулевой/непосчитанный балл не абитуриент
            rows.append(DirectionRow(
                position=a.get("rating"),
                unique_code=str(code),
                total_score=score,
                priority=a.get("priority"),
                consent=(a.get("consent") not in (None, "NONE")),
            ))

        directions.append(DirectionResult(
            name=info["name"], fgos_code=info["fgos_code"], seats=info["seats"],
            group_id=group_id, rows=rows,
        ))

    return directions
