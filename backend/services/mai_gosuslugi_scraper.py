"""Списки МАИ из публичного API Госуслуг.

Это отдельный источник от priem.mai.ru: Госуслуги отдают более широкий поток
заявлений и статусов, поэтому сохраняем его как отдельный university.
"""
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from config import (
    BAUMAN_API_BASE, BAUMAN_ITEMS_URL, MAI_GOSUSLUGI_HTTP_HEADERS,
    MAI_GOSUSLUGI_ORG_ID, MAI_GOSUSLUGI_TARGET_CODES, REQUEST_TIMEOUT, RETRIES,
)

session = requests.Session()
session.headers.update(MAI_GOSUSLUGI_HTTP_HEADERS)


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


def _normalize_okso(code: str) -> str:
    code = code or ""
    return code[2:] if code.startswith("2.") else code


def _to_score(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def select_target_items(items: list) -> list[DirectionResult]:
    selected = []
    for item in items:
        code = _normalize_okso(item.get("oksoCode") or "")
        if code not in MAI_GOSUSLUGI_TARGET_CODES:
            continue
        if item.get("educationLevelName") != "Базовое высшее образование":
            continue
        if item.get("educationFormName") != "Очная":
            continue
        if item.get("placeTypeName") != "Основные места в рамках КЦП":
            continue
        selected.append(DirectionResult(
            name=item.get("oksoName") or code,
            fgos_code=code or None,
            seats=item.get("numberPlaces"),
            group_id=item["id"],
        ))
    return selected


def rows_from_applicants(applicants: list) -> list[DirectionRow]:
    rows = []
    for applicant in applicants:
        code = applicant.get("idApplication")
        score = _to_score(applicant.get("sumMark"))
        if code is None or not score:
            continue
        rows.append(DirectionRow(
            position=applicant.get("rating"),
            unique_code=str(code),
            total_score=score,
            priority=applicant.get("priority"),
            consent=(applicant.get("consent") not in (None, "NONE")),
        ))
    return rows


def _fetch_program_items() -> list:
    return _request_json(
        "post",
        BAUMAN_ITEMS_URL,
        params={"page": 0, "size": 500},
        json={"orgId": MAI_GOSUSLUGI_ORG_ID},
    )


def _fetch_applicants(group_id: int) -> list:
    data = _request_json("get", f"{BAUMAN_API_BASE}/competition/{group_id}/applicants")
    return data.get("applicants", [])


def scrape_scope() -> list[DirectionResult]:
    directions = select_target_items(_fetch_program_items())
    if not directions:
        raise ScrapeError("Госуслуги не вернули целевые конкурсные группы МАИ")

    for direction in directions:
        direction.rows = rows_from_applicants(_fetch_applicants(direction.group_id))
    return directions
