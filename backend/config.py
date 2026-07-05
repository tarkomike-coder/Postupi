import os

BASE_LIST_URL = "https://priem.mai.ru/list/"
DATA_URL = "https://public.mai.ru/priem/list/data/{token}.html"
SEAT_PLAN_URL = "https://priem.mai.ru/orders/plan/common/"

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": BASE_LIST_URL,
}

# Наш scope (см. обсуждение): только эта комбинация фильтров МАИ.
SCOPE_PLACE = "МАИ"
SCOPE_LEVEL = "Базовое высшее образование"
SCOPE_FORM = "Очная"
SCOPE_PAY = "Бюджет"

# Категория, которую использует симуляция (остальные категории на той же
# странице всё равно сохраняются в БД - вдруг понадобятся позже).
SIM_CATEGORY = "Лица, поступающие по общему конкурсу"

# Секция в orders/plan/common/, к которой относятся места нашего уровня.
SEAT_PLAN_SECTION_MARKER = "базового высшего образования"

DEFAULT_TARGET_CODE = "1422086"
DEFAULT_TARGET_NAME = "Варя"

# --- Бауманка (МГТУ им. Баумана), через публичный (без логина) JSON API
# Госуслуг "Вуз-навигатор". Механика разобрана вручную через браузер, см.
# services/bauman_scraper.py. groupId нельзя перечислить одним запросом -
# единственный найденный способ узнать его: открыть в браузере
# https://www.gosuslugi.ru/vuznavigator/specialties/{oksoCode}/{levelId}/26
# (oksoCode формата "2.09.03.01", levelId=6 - "Базовое высшее образование"
# у Баумана в 2026 году) и посмотреть, какие groupId она подставляет в
# запрос .../competition/statuses/ratings. Поэтому список ниже - руками
# найденные и проверенные (по applicationId Вари) id; если появится новое
# направление, добавить его сюда тем же способом.
BAUMAN_ORG_ID = 26
BAUMAN_API_BASE = "https://www.gosuslugi.ru/api/university-applicant-list/v1/public/2026"
BAUMAN_ITEMS_URL = "https://www.gosuslugi.ru/api/vuz-navigator/public/v1/2026/educational-programs/items"
BAUMAN_GROUP_IDS = [128864, 128989]
BAUMAN_HTTP_HEADERS = {
    "User-Agent": HTTP_HEADERS["User-Agent"],
    "Referer": "https://www.gosuslugi.ru/vuznavigator/universities/26",
    "Accept": "application/json",
}

_DEFAULT_SQLITE_PATH = os.path.join(os.path.dirname(__file__), "postupi.db")
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{_DEFAULT_SQLITE_PATH}")

REQUEST_TIMEOUT = 15
RETRIES = 3
MAX_WORKERS = 8

# Monte Carlo приоры (константы для v1, см. обсуждение - калибровка по
# истории откладывается на v2).
MC_TRIALS = 500
MC_P3_NO_CONSENT_JOINS = 0.30   # вероятность, что человек без согласия всё же подаст его
MC_P4_CONSENT_DROPS_OUT = 0.15  # вероятность, что человек с согласием реально уйдёт в другой вуз

RAW_SNAPSHOTS_TO_KEEP = 3
RAW_SNAPSHOTS_DIR = os.environ.get(
    "RAW_SNAPSHOTS_DIR",
    os.path.join(os.path.dirname(__file__), "raw_snapshots"),
)

SCHEDULE_TIMES_MSK = ["09:00", "21:00"]  # 2 раза в день
