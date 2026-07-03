"""
Скрипт для поиска абитуриента по "Уникальному коду" во всех конкурсных списках
приёмной комиссии МАИ (https://priem.mai.ru/list/).

Как это работает (реверс-инжиниринг фронтенда):
  Страница https://priem.mai.ru/list/ содержит каскад из 5 <select>:
    Площадка -> Уровень подготовки -> Направление подготовки -> Форма обучения -> Основа обучения
  При выборе каждого значения jQuery дёргает:
    https://public.mai.ru/priem/list/data/<TOKEN>.html
  TOKEN устраивается как "p<generation_id>_<place>_l<level>_s<spec>_f<form>_p<pay>",
  где <generation_id> - идентификатор текущего "среза" данных (снимок конкурсных
  списков), зашитый в HTML при загрузке /list/, и общий для всех посетителей
  в данный момент времени (не привязан к cookie/сессии конкретного браузера).
  Никакой капчи или авторизации не требуется - это обычные статические HTML-
  фрагменты, отдаваемые nginx, без токенов CSRF.

Итоговый фрагмент (уровень "pay") - это одна или несколько HTML-таблиц
(БВИ / особая квота / целевая квота / общий конкурс), где 2-я колонка -
"Уникальный код" (это и есть номер заявления абитуриента).
"""
import csv
import re
import sys
import time
import concurrent.futures as cf
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

BASE_LIST_URL = "https://priem.mai.ru/list/"
DATA_URL = "https://public.mai.ru/priem/list/data/{token}.html"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": BASE_LIST_URL,
}

TARGET_CODE = "1422086"   # искомый уникальный код абитуриента
MAX_WORKERS = 8            # разумная параллельность, чтобы не долбить сервер
REQUEST_TIMEOUT = 15
RETRIES = 3


session = requests.Session()
session.headers.update(HEADERS)


def fetch(url: str) -> str:
    last_exc = None
    for attempt in range(RETRIES):
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                # Сервер не указывает charset в Content-Type, requests из-за
                # этого иногда угадывает кодировку неверно (латиница вместо
                # utf-8) - декодируем байты сами.
                return r.content.decode("utf-8", errors="replace")
            last_exc = RuntimeError(f"HTTP {r.status_code} for {url}")
        except requests.RequestException as e:
            last_exc = e
        time.sleep(0.5 * (attempt + 1))
    raise last_exc


def parse_options(html: str):
    """Достаёт список (value, label) из фрагмента <option>...</option>."""
    soup = BeautifulSoup(html, "lxml")
    result = []
    for opt in soup.find_all("option"):
        val = opt.get("value")
        label = opt.get_text(strip=True)
        if val and val != "0":
            result.append((val, label))
    return result


def get_root_token_and_places():
    html = fetch(BASE_LIST_URL)
    places = parse_options(html)
    if not places:
        raise RuntimeError("Не удалось найти список площадок на странице /list/ "
                            "- возможно, вёрстка сайта изменилась.")
    return places


@dataclass
class Branch:
    place_token: str
    place: str
    level_token: str = ""
    level: str = ""
    spec_token: str = ""
    spec: str = ""
    form_token: str = ""
    form: str = ""
    pay_token: str = ""
    pay: str = ""


def crawl_options(token: str):
    """Универсальный шаг каскада: получить опции следующего select по токену."""
    url = DATA_URL.format(token=token)
    html = fetch(url)
    return parse_options(html)


def build_all_pay_branches(places):
    """Последовательно обходит все 4 уровня каскада и возвращает список
    финальных "веток" (площадка+уровень+направление+форма+основа),
    для которых нужно скачать итоговую таблицу конкурсного списка."""
    branches = []

    def worker_levels(place_token, place):
        try:
            levels = crawl_options(place_token)
        except Exception as e:
            print(f"  ! Уровни для площадки {place}: ошибка {e}", file=sys.stderr)
            return []
        return [(place_token, place, lt, ll) for lt, ll in levels]

    def worker_specs(args):
        place_token, place, level_token, level = args
        try:
            specs = crawl_options(level_token)
        except Exception as e:
            print(f"  ! Направления для {place}/{level}: ошибка {e}", file=sys.stderr)
            return []
        return [(place_token, place, level_token, level, st, sl) for st, sl in specs]

    def worker_forms(args):
        place_token, place, level_token, level, spec_token, spec = args
        try:
            forms = crawl_options(spec_token)
        except Exception as e:
            print(f"  ! Формы для {place}/{level}/{spec}: ошибка {e}", file=sys.stderr)
            return []
        return [(place_token, place, level_token, level, spec_token, spec, ft, fl)
                for ft, fl in forms]

    def worker_pays(args):
        (place_token, place, level_token, level, spec_token, spec,
         form_token, form) = args
        try:
            pays = crawl_options(form_token)
        except Exception as e:
            print(f"  ! Основы обучения для {place}/{level}/{spec}/{form}: ошибка {e}",
                  file=sys.stderr)
            return []
        return [Branch(place_token, place, level_token, level, spec_token, spec,
                        form_token, form, pt, pl) for pt, pl in pays]

    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        level_lists = list(ex.map(worker_levels, [p[0] for p in places], [p[1] for p in places]))
    level_items = [x for sub in level_lists for x in sub]
    print(f"Найдено уровней подготовки (всего по всем площадкам): {len(level_items)}")

    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        spec_lists = list(ex.map(worker_specs, level_items))
    spec_items = [x for sub in spec_lists for x in sub]
    print(f"Найдено направлений подготовки (всего): {len(spec_items)}")

    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        form_lists = list(ex.map(worker_forms, spec_items))
    form_items = [x for sub in form_lists for x in sub]
    print(f"Найдено комбинаций направление+форма: {len(form_items)}")

    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        pay_lists = list(ex.map(worker_pays, form_items))
    branches = [x for sub in pay_lists for x in sub]
    print(f"Найдено финальных списков (направление+форма+основа): {len(branches)}")

    return branches


def parse_final_table(html: str, branch: Branch):
    """Разбирает итоговый HTML со списком поступающих. Внутри может быть
    несколько таблиц (БВИ / особая квота / целевая квота / общий конкурс)."""
    soup = BeautifulSoup(html, "lxml")

    updated_match = re.search(r"Дата последнего обновления:\s*([^\n<]+)", html)
    updated = updated_match.group(1).strip() if updated_match else ""

    rows_out = []
    # категория - ближайший предшествующий <b> перед каждой таблицей
    for table in soup.find_all("table"):
        category = ""
        prev = table.find_previous(["b"])
        if prev:
            category = prev.get_text(strip=True)

        header_cells = [th.get_text(strip=True) for th in table.find("tr").find_all("th")]
        body_rows = table.find_all("tr")[1:]
        total = len(body_rows)
        for tr in body_rows:
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) < 2:
                continue
            row = dict(zip(header_cells, cells))
            row["_category"] = category
            row["_position"] = cells[0]
            row["_unique_code"] = cells[1]
            row["_total_in_group"] = total
            row["_updated"] = updated
            rows_out.append(row)
    return rows_out


def search_branch(branch: Branch):
    url = DATA_URL.format(token=branch.pay_token)
    try:
        html = fetch(url)
    except Exception as e:
        return branch, [], f"ошибка запроса: {e}"
    rows = parse_final_table(html, branch)
    matches = [r for r in rows if r.get("_unique_code") == TARGET_CODE]
    return branch, matches, None


def main():
    print(f"Ищем уникальный код {TARGET_CODE} во всех конкурсных списках МАИ...")
    print("Шаг 1: получаем список площадок...")
    places = get_root_token_and_places()
    for v, l in places:
        print(f"  - {l}  ({v})")

    print("Шаг 2: обходим весь каскад фильтров (площадка -> уровень -> "
          "направление -> форма -> основа обучения)...")
    branches = build_all_pay_branches(places)

    print(f"Шаг 3: скачиваем и парсим {len(branches)} итоговых списков "
          f"(параллельно, {MAX_WORKERS} потоков)...")

    found = []
    errors = []
    done = 0
    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(search_branch, b) for b in branches]
        for fut in cf.as_completed(futures):
            branch, matches, err = fut.result()
            done += 1
            if done % 50 == 0 or done == len(branches):
                print(f"  ...обработано {done}/{len(branches)}")
            if err:
                errors.append((branch, err))
                continue
            for m in matches:
                found.append((branch, m))

    print()
    print("=" * 100)
    if not found:
        print(f"Код {TARGET_CODE} НЕ найден ни в одном из {len(branches)} "
              f"проверенных списков.")
    else:
        print(f"Код {TARGET_CODE} найден в {len(found)} списках:")
        print()
        fieldnames = ["Площадка", "Уровень", "Направление", "Форма", "Основа",
                      "Категория", "Позиция", "Всего в группе", "Сумма баллов",
                      "Приоритет", "Согласие", "Обновлено"]
        csv_rows = []
        for branch, m in found:
            consent = m.get("Согласие", "")
            score = m.get("Сумма баллов", "")
            priority = m.get("Приоритет", "")
            print(f"* {branch.place} | {branch.level} | {branch.spec} | "
                  f"{branch.form} | {branch.pay} | {m.get('_category')}")
            print(f"    Позиция: {m['_position']} из {m['_total_in_group']}  "
                  f"Баллы: {score}  Приоритет: {priority}  Согласие: {consent}")
            csv_rows.append({
                "Площадка": branch.place, "Уровень": branch.level,
                "Направление": branch.spec, "Форма": branch.form,
                "Основа": branch.pay, "Категория": m.get("_category", ""),
                "Позиция": m["_position"], "Всего в группе": m["_total_in_group"],
                "Сумма баллов": score, "Приоритет": priority,
                "Согласие": consent, "Обновлено": m.get("_updated", ""),
            })
        out_path = "mai_result.csv"
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(csv_rows)
        print()
        print(f"Результаты сохранены в {out_path}")

    if errors:
        print()
        print(f"Предупреждение: {len(errors)} списков не удалось скачать/разобрать.")


if __name__ == "__main__":
    main()
