"""Скрейпер конкурсных списков priem.mai.ru, суженный на наш scope:
площадка=МАИ, уровень=Базовое высшее образование, форма=Очная, основа=Бюджет.

Механика сайта разобрана в C:\\Projects\\Postupi\\mai_scraper.py (черновой
скрипт первого исследования) - здесь та же логика, но без полного перебора
всех уровней/площадок, только нужная ветка, и с сохранением ВСЕХ категорий
таблицы (БВИ/особая квота/целевая квота/общий конкурс), которые приходят на
той же странице бесплатно.
"""
import re
import time
import concurrent.futures as cf
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup

from config import (
    BASE_LIST_URL, DATA_URL, HTTP_HEADERS, REQUEST_TIMEOUT, RETRIES,
    MAX_WORKERS, SCOPE_PLACE, SCOPE_LEVEL, SCOPE_FORM, SCOPE_PAY,
)

session = requests.Session()
session.headers.update(HTTP_HEADERS)


class ScrapeError(RuntimeError):
    pass


def fetch(url: str) -> str:
    last_exc = None
    for attempt in range(RETRIES):
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                return r.content.decode("utf-8", errors="replace")
            last_exc = ScrapeError(f"HTTP {r.status_code} for {url}")
        except requests.RequestException as e:
            last_exc = e
        time.sleep(0.5 * (attempt + 1))
    raise last_exc


def parse_options(html: str):
    soup = BeautifulSoup(html, "lxml")
    return [
        (opt.get("value"), opt.get_text(strip=True))
        for opt in soup.find_all("option")
        if opt.get("value") and opt.get("value") != "0"
    ]


def find_option(options, label: str) -> Optional[str]:
    for value, text in options:
        if text.strip() == label:
            return value
    return None


@dataclass
class DirectionRow:
    position: Optional[int]
    unique_code: str
    total_score: Optional[int]
    priority: Optional[int]
    consent: bool


@dataclass
class CategoryTable:
    category: str
    updated_at_source: str
    rows: list = field(default_factory=list)


@dataclass
class DirectionResult:
    name: str
    pay_token: str
    category_tables: list  # list[CategoryTable]
    raw_html: str


def _parse_int(text: str) -> Optional[int]:
    text = text.strip()
    if not text or text in ("0", "-"):
        return 0 if text == "0" else None
    m = re.search(r"-?\d+", text)
    return int(m.group()) if m else None


def parse_final_list_html(html: str) -> list:
    """Разбирает HTML со списком поступающих на направление -> список
    CategoryTable (может быть несколько таблиц: БВИ/квоты/общий конкурс)."""
    soup = BeautifulSoup(html, "lxml")
    tables_out = []

    for table in soup.find_all("table"):
        category = ""
        prev_b = table.find_previous("b")
        if prev_b:
            category = prev_b.get_text(strip=True)

        updated_match = re.search(r"Дата последнего обновления:\s*([^\n<]+)", html)
        updated = updated_match.group(1).strip() if updated_match else ""

        header_row = table.find("tr")
        if not header_row:
            continue
        headers = [th.get_text(strip=True) for th in header_row.find_all("th")]

        rows = []
        for tr in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) < 2:
                continue
            row = dict(zip(headers, cells))
            rows.append(DirectionRow(
                position=_parse_int(cells[0]),
                unique_code=cells[1],
                total_score=_parse_int(row.get("Сумма баллов", "")),
                priority=_parse_int(row.get("Приоритет", "")),
                consent=bool(row.get("Согласие", "").strip()),
            ))

        tables_out.append(CategoryTable(category=category, updated_at_source=updated, rows=rows))

    return tables_out


def scrape_scope():
    """Возвращает (generation_token, [DirectionResult, ...]) для всего
    нашего scope (все направления под МАИ/Базовое высшее образование/
    Очная/Бюджет)."""
    root_html = fetch(BASE_LIST_URL)
    places = parse_options(root_html)
    place_token = find_option(places, SCOPE_PLACE)
    if not place_token:
        raise ScrapeError(f"Площадка '{SCOPE_PLACE}' не найдена в фильтре сайта")

    generation_token = place_token.split("_")[0]  # "p20260703124211"

    levels = parse_options(fetch(DATA_URL.format(token=place_token)))
    level_token = find_option(levels, SCOPE_LEVEL)
    if not level_token:
        raise ScrapeError(f"Уровень '{SCOPE_LEVEL}' не найден в фильтре сайта")

    specs = parse_options(fetch(DATA_URL.format(token=level_token)))
    if not specs:
        raise ScrapeError("Список направлений пуст - возможно, вёрстка сайта изменилась")

    def resolve_pay_token(spec_token_and_name):
        spec_token, spec_name = spec_token_and_name
        try:
            forms = parse_options(fetch(DATA_URL.format(token=spec_token)))
            form_token = find_option(forms, SCOPE_FORM)
            if not form_token:
                return None
            pays = parse_options(fetch(DATA_URL.format(token=form_token)))
            pay_token = find_option(pays, SCOPE_PAY)
            if not pay_token:
                return None
            return (spec_name, pay_token)
        except Exception:
            return None

    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        resolved = list(ex.map(resolve_pay_token, specs))
    resolved = [r for r in resolved if r]

    def fetch_direction(name_and_token):
        name, pay_token = name_and_token
        html = fetch(DATA_URL.format(token=pay_token))
        tables = parse_final_list_html(html)
        return DirectionResult(name=name, pay_token=pay_token, category_tables=tables, raw_html=html)

    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        directions = list(ex.map(fetch_direction, resolved))

    return generation_token, directions
