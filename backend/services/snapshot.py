"""Генерация статической страницы postupi с вшитыми данными.

После синка собираем те же данные, что отдают API-эндпоинты (через общие
build_*-функции - единый источник правды), и вшиваем их в готовый index.html.
Посетитель грузит один статический файл, без запросов к API - нечему висеть
на «Загрузка…» на слабой мобильной сети.
"""
from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from api.postupi import build_events, build_history, build_status, list_universities
from config import POSTUPI_SITE_TEMPLATE, POSTUPI_WEB_ROOT
from database.db import SessionLocal

_MARKER = re.compile(r'<script id="postupi-snapshot">.*?</script>', re.DOTALL)


def build_snapshot(db) -> dict:
    """Собрать снапшот по всем вузам. Падение одного вуза не рушит остальные."""
    unis = list_universities(db).get("universities", [])
    # МАИ первым, остальные по алфавиту - как показывает фронт.
    ordered = (["МАИ"] if "МАИ" in unis else []) + sorted(u for u in unis if u != "МАИ")
    universities = []
    for name in ordered:
        entry: dict = {"name": name}
        try:
            entry["status"] = build_status(db, name)
            entry["history"] = build_history(db, name)
            entry["events"] = build_events(db, name)
        except HTTPException as exc:
            entry["error"] = exc.detail
        universities.append(entry)
    return {"generated_at": datetime.now(UTC).isoformat(), "universities": universities}


def _inject(template_html: str, snapshot: dict) -> str:
    payload = json.dumps(jsonable_encoder(snapshot), ensure_ascii=False)
    # Экранируем, чтобы данные не могли сломать <script> или вставить разметку.
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    block = f'<script id="postupi-snapshot">window.__SNAPSHOT__ = {payload};</script>'
    if _MARKER.search(template_html):
        return _MARKER.sub(lambda _: block, template_html)
    # Плейсхолдера в шаблоне нет - вставляем перед </head> (до основного скрипта).
    return template_html.replace("</head>", block + "\n</head>", 1)


def generate(db=None) -> str:
    """Собрать снапшот и записать готовый index.html в POSTUPI_WEB_ROOT.

    Возвращает путь к записанному файлу. Запись атомарная (через .tmp + replace).
    """
    own = db is None
    if own:
        db = SessionLocal()
    try:
        snapshot = build_snapshot(db)
    finally:
        if own:
            db.close()

    with open(POSTUPI_SITE_TEMPLATE, encoding="utf-8") as f:
        template = f.read()
    html = _inject(template, snapshot)

    os.makedirs(POSTUPI_WEB_ROOT, exist_ok=True)
    out_path = os.path.join(POSTUPI_WEB_ROOT, "index.html")
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(html)
    os.replace(tmp_path, out_path)
    return out_path


def regenerate_safe(db=None) -> str | None:
    """Пересобрать страницу; падение генерации не должно рушить синк."""
    try:
        out = generate(db=db)
        print(f"SNAPSHOT regenerated: {out}")
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"SNAPSHOT generation failed: {exc}")
        return None


if __name__ == "__main__":
    print("generated:", generate())
