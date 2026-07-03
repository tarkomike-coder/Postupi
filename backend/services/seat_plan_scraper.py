"""Парсинг orders/plan/common/ - КЦП (бюджетные места). Страница содержит
ОДНУ большую таблицу, разбитую на секции по уровню подготовки строками-
заголовками вида <td colspan="3"><b>Программы базового высшего образования
(4 года)</b></td>. Нужно матчить места именно из нужной секции, т.к. одно и
то же название направления может повторяться в разных уровнях с разными
цифрами."""
import re

from bs4 import BeautifulSoup

from config import SEAT_PLAN_URL, SEAT_PLAN_SECTION_MARKER
from services.mai_list_scraper import fetch


def _is_section_header_row(tr) -> str:
    tds = tr.find_all("td")
    if len(tds) == 1 and tds[0].get("colspan"):
        b = tds[0].find("b")
        if b:
            return b.get_text(strip=True)
    return ""


def scrape_seat_plan() -> dict:
    """Возвращает {направление_name: seats_int} только для нужной секции
    (SEAT_PLAN_SECTION_MARKER)."""
    html = fetch(SEAT_PLAN_URL)
    soup = BeautifulSoup(html, "lxml")

    result = {}
    current_section = ""
    in_target_section = False

    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            header_text = _is_section_header_row(tr)
            if header_text:
                current_section = header_text
                in_target_section = SEAT_PLAN_SECTION_MARKER.lower() in header_text.lower()
                continue

            if not in_target_section:
                continue

            tds = tr.find_all("td")
            if len(tds) != 3:
                continue

            name = tds[0].get_text(strip=True)
            code = tds[1].get_text(strip=True)
            seats_text = tds[2].get_text(strip=True)
            m = re.search(r"\d+", seats_text)
            if not name or not m:
                continue
            result[name] = {"seats": int(m.group()), "fgos_code": code}

    return result
