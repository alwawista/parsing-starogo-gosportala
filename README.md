# Парсер ГРКИ (Росreestr)

Консольный Python-скрипт для сбора данных из личных карточек кадастровых инженеров с официального сайта Росreestr (rosreestr.gov.ru).

## Возможности

- Сбор данных в **4 связанных CSV-таблицы** (ключ — `регистрационный_номер`)
- Playwright для обхода защиты сайта + BeautifulSoup4 для разбора HTML
- **Чекпоинты** — прогресс сохраняется после каждой карточки
- **Логирование ошибок** в `data/errors.log` без остановки парсера
- Поддержка **ротируемых прокси** через переменную окружения

## Структура проекта

```
GRKI-Rosreestr-scraping/
├── config.py                 # Настройки (пути, таймауты, URL)
├── main.py                   # Точка входа
├── grki_scraper/
│   ├── browser.py            # Playwright-сессия
│   ├── checkpoint.py         # Сохранение прогресса
│   ├── logger.py             # errors.log
│   ├── extractors/
│   │   ├── list_extractor.py # Таблица реестра
│   │   └── detail_extractor.py # Карточка инженера
│   └── writers/
│       └── csv_writer.py     # Запись CSV
├── data/
│   ├── input/                # Входной CSV (режим csv)
│   ├── output/               # Результаты
│   ├── checkpoint.json       # Прогресс
│   └── errors.log            # Ошибки
├── requirements.txt
└── EnvExample
```

## Сетевой endpoint (результат probe)

Отдельного JSON/AJAX API для вкладки «Результаты профессиональной деятельности» **нет** — при клике новых `xhr`/`fetch` не появляется, таблица уже в HTML карточки (клиентский показ/скрытие).

| Назначение | Метод | URL |
|------------|-------|-----|
| Список реестра КИ | `GET` | `...QCB2freestr.do==/?reestr=9` |
| Карточка инженера | `GET` | `...QCB2fperson_view.do==/?id={person_id}&sroId=&excluded=false&filterName=personFilter` |

Ответ карточки: **`text/html; charset=UTF-8`** (не JSON). Прямой `GET` возможен через `playwright.request` после визита списка (cookies); голый запрос без сессии может отдать урезанную страницу.

Диагностика:

```bash
# ContactFlow (Node)
cd parser/node_scripts
node rosreestr_probe.cjs --person-id 824174
node rosreestr_replay.cjs --person-id 824174

# GRKI (Python)
python rosreestr_network_probe.py --person-id 824174 --replay
```

Логи: `ContactFlow/outputs/rosreestr_probe_log.json`, `GRKI-Rosreestr-scraping/data/rosreestr_probe_log.json`.

## Установка

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Скопируйте `EnvExample` в `.env` и при необходимости измените параметры.

## Запуск

### Тестовый срез (первые 50 строк с сайта)

```bash
python main.py
```

По умолчанию: `SCRAPE_MODE=listing`, `ROW_LIMIT=50`.

### Полный прогон по входному CSV (~40 000 записей)

1. Положите файл `data/input/engineers_source.csv` с колонками:
   `фамилия;имя;отчество;регистрационный_номер;статус;дата_регистрации`
2. Опционально добавьте колонку `person_id` (внутренний ID сайта для прямых ссылок)
3. В `.env` установите:

```env
SCRAPE_MODE=csv
ROW_LIMIT=0
```

4. Запустите:

```bash
python main.py
```

При отсутствии `person_id` парсер построит маппинг с первых страниц реестра.

## Выходные файлы (`data/output/`)

| Файл | Описание |
|------|----------|
| `engineers.csv` | Основная таблица (10 колонок) |
| `sro_history.csv` | История членства в СРО |
| `disciplinary_actions.csv` | Дисциплинарные воздействия |
| `professional_activity.csv` | Результаты профессиональной деятельности |

Формат: **UTF-8 с BOM** (`utf-8-sig`), разделитель **`;`**, **QUOTE_ALL** (все поля в двойных кавычках).  
Excel на Windows открывает такие файлы двойным щелчком без «кракозябр».

**Пустые значения:** при отсутствии данных записывается пустое значение Python (`""`), без `NaN`, `null` и других служебных строк. Так как CSV формируется с `QUOTE_ALL`, пустые поля сериализуются как `""` — это корректный CSV, который при импорте в PostgreSQL маппится на `NULL` (например, через `COPY ... NULL ''`).

## Возобновление после сбоя

Парсер автоматически пропускает уже обработанные `регистрационный_номер` из `data/checkpoint.json`.  
Для полного перезапуска удалите `checkpoint.json` и CSV в `data/output/`.

## Прокси

```env
PROXY_LIST=http://user:pass@host:8080,socks5://host:1080
```

При сетевой ошибке парсер переключается на следующий прокси из списка.

## Интеграция с PostgreSQL

Модули `extractors/` возвращают dataclass-структуры, а `writers/csv_writer.py` — только запись в файлы.  
Для загрузки в БД достаточно заменить слой `writers` на INSERT в PostgreSQL, сохранив экстракторы без изменений.

## Для backend-разработчика

### Точки входа

| Файл | Назначение |
|------|------------|
| `main.py` → `asyncio.run(main())` | CLI-запуск |
| `main.py` → `process_card()` | Обработка одной карточки (удобно обернуть в Celery-task) |
| `main.py` → `collect_listing_rows()` | Сбор списка без детализации |
| `extract_detail_card(html)` | Чистый парсинг HTML карточки без браузера |

### Поток данных

```
config.py          ← env / .env
    ↓
BrowserSession     ← Playwright: список + карточки
    ↓ HTML
extractors/        ← BeautifulSoup → dataclass
    ↓
writers/           ← CSV (или ваш PostgreSQL-writer)
    ↓
checkpoint + logger
```

### Модули

- **`browser.py`** — навигация, пагинация `setPage()`, ротация прокси при сбое
- **`extractors/`** — разбор HTML; не пишет на диск, не знает про CSV
- **`writers/csv_writer.py`** — сериализация; `QUOTE_ALL`, пустые → `""`
- **`checkpoint.py`** — resume после падения; ключ — `регистрационный_номер`
- **`logger.py`** — ошибки по карточкам без остановки прогона

### Docker / Celery

Проект не монолитный скрипт: логика разнесена по папкам. Для Docker достаточно:

```dockerfile
RUN python -m playwright install --with-deps chromium
CMD ["python", "main.py"]
```

Celery-задача может вызывать `process_card()` для батчей или `run_csv_mode()` целиком.

### Комментарии в коде

Комментарии стоят в ключевых местах (навигация, extractors, checkpoint/retry, экспорт, ошибки).  
Акцент — на модульную структуру и читаемость, без избыточного docstring на каждую функцию.
