"""
Конфигурация парсера ГРКИ (Росреестр).

Все изменяемые параметры собраны здесь для удобной настройки
перед интеграцией в бэкенд с PostgreSQL.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Базовые пути ---
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"
# --- Выходные CSV (разделитель — точка с запятой, UTF-8) ---
# OUTPUT_SUFFIX=500 → engineers500.csv, checkpoint500.json и т.д.
OUTPUT_SUFFIX = os.getenv("OUTPUT_SUFFIX", "").strip()
_suffix = f"{OUTPUT_SUFFIX}" if OUTPUT_SUFFIX else ""

ENGINEERS_CSV = OUTPUT_DIR / f"engineers{_suffix}.csv"
SRO_HISTORY_CSV = OUTPUT_DIR / f"sro_history{_suffix}.csv"
DISCIPLINARY_CSV = OUTPUT_DIR / f"disciplinary_actions{_suffix}.csv"
PROFESSIONAL_ACTIVITY_CSV = OUTPUT_DIR / f"professional_activity{_suffix}.csv"

CHECKPOINT_FILE = DATA_DIR / (f"checkpoint{_suffix}.json" if _suffix else "checkpoint.json")
ERROR_LOG_FILE = DATA_DIR / (f"errors{_suffix}.log" if _suffix else "errors.log")

# --- Входной CSV (режим полного парсинга по списку рег. номеров) ---
INPUT_CSV = INPUT_DIR / "engineers_source.csv"

# --- URL реестра кадастровых инженеров (reestr=9) ---
LIST_URL = os.getenv(
    "LIST_URL",
    "https://rosreestr.gov.ru/wps/portal/p/cc_ib_portal_services/cc_ib_sro_reestrs/"
    "!ut/p/z1/04_Sj9CPykssy0xPLMnMz0vMAfIjo8ziDQw9HA0dTYy8_U09XQwCTUzN_Py8fI0NDAz0w8EK3ANNXA2dTQy93QMNzQ0cPR29DY0N3Q0M_A31o4jRj0cBWD8O4AjSHwVWgssFzkYEFICcSMiSgtzQCINMT0UAZsE4jA!!/"
    "p0/IZ7_01HA1A42KO5ID0Q456NNJM30G4=CZ6_01HA1A42KO5ID0Q456NNJM3000=LA0="
    "Espf_ActionName!spf_ActionListener=spf_strutsAction!QCB2freestr.do==/?reestr=9",
)

DETAIL_URL_TEMPLATE = os.getenv(
    "DETAIL_URL_TEMPLATE",
    "https://rosreestr.gov.ru/wps/portal/p/cc_ib_portal_services/cc_ib_sro_reestrs/"
    "!ut/p/z1/jZDNDoIwEISfxQNXd1eqEG-NmqrEHw4G7MVggpWA1NSiry9gvIm6t918k50ZkBCDLJN7phKb6TIp6n0vRwekOSfOBsFmuJhiyIaj9Xq5chERohYQIZvRhFEgQvKQL3hALgnEDYH8R_8FaPUdwxu9bJEuB5PBD6Cx-OvJEqQq9PHVBy-Prq9AmvSUmtT0K1Ofz9Zeb2MHHcwf2uR9Uzn4CT7rm4X4zcC-Tu91phcMrpddjNn2EvnWV7zXewLHvu7R/p0/"
    "IZ7_01HA1A42KO5ID0Q456NNJM30G4=CZ6_01HA1A42KO5ID0Q456NNJM3000=LA0="
    "Espf_ActionName!spf_ActionListener=spf_strutsAction!QCB2fperson_view.do==/?id={person_id}&sroId=&excluded=false&filterName=personFilter",
)

# --- Режим работы ---
# "listing" — собрать первые N строк из таблицы реестра на сайте
# "csv" — обработать рег. номера из входного CSV
SCRAPE_MODE = os.getenv("SCRAPE_MODE", "listing")

# Лимит записей для тестового среза (0 = без ограничений)
ROW_LIMIT = int(os.getenv("ROW_LIMIT", "50"))

# --- Браузер (Playwright) ---
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
IGNORE_HTTPS_ERRORS = os.getenv("IGNORE_HTTPS_ERRORS", "true").lower() == "true"
PAGE_LOAD_TIMEOUT_MS = int(os.getenv("PAGE_LOAD_TIMEOUT_MS", "120000"))
NAVIGATION_WAIT = os.getenv("NAVIGATION_WAIT", "domcontentloaded")  # networkidle | domcontentloaded
POST_LOAD_DELAY_MS = int(os.getenv("POST_LOAD_DELAY_MS", "1500"))

# --- Задержки между запросами (снижение нагрузки на сайт) ---
DELAY_BETWEEN_CARDS_MS = int(os.getenv("DELAY_BETWEEN_CARDS_MS", "800"))
DELAY_BETWEEN_PAGES_MS = int(os.getenv("DELAY_BETWEEN_PAGES_MS", "1000"))

# --- Прокси (опционально) ---
# PROXY_LIST — список через запятую: http://user:pass@host:port,socks5://host:port
PROXY_LIST = [
    p.strip()
    for p in os.getenv("PROXY_LIST", "").split(",")
    if p.strip()
]

# --- Формат CSV ---
# utf-8-sig = UTF-8 с BOM; Excel на Windows открывает кириллицу корректно
CSV_ENCODING = "utf-8-sig"
CSV_DELIMITER = ";"
ENGINEERS_COLUMNS = [
    "фамилия",
    "имя",
    "отчество",
    "регистрационный_номер",
    "статус",
    "дата_регистрации",
    "номер_аттестата",
    "дата_аттестата",
    "реестровый_номер_СРО",
    "текущая_дата_членства_в_СРО",
]

SRO_HISTORY_COLUMNS = [
    "регистрационный_номер",
    "наименование_СРО",
    "дата_включения",
    "дата_исключения",
    "основание_исключения",
]

DISCIPLINARY_COLUMNS = [
    "регистрационный_номер",
    "мера_ДВ",
    "дата_решения",
    "основание_применения",
    "дата_началу_ДВ",
    "дата_окончания_ДВ",
]

PROFESSIONAL_ACTIVITY_COLUMNS = [
    "регистрационный_номер",
    "год",
    "период",
    "решений_об_осуществлении_и_отказе",
    "отказов_по_статье_27",
    "решений_об_устранении_ошибок",
    "решений_о_приостановлении",
]
