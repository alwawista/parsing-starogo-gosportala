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

## Исследования и тесты (probe)

Перед полным прогоном (~37–40k карточек) провели серию диагностических скриптов на живом сайте. Итоги зафиксированы в `data/*.json`; pytest покрывает экстрактор и CSV-писатель.

| # | Тема | Скрипт | Отчёт | Вердикт |
|---|------|--------|-------|---------|
| 0 | Сетевой API карточки | `rosreestr_network_probe.py` | `data/rosreestr_probe_log.json` | Отдельного JSON/AJAX для вкладок **нет** — таблицы уже в HTML `GET` |
| 1 | TTL сессии `!ut/p/z1/...` | `rosreestr_session_ttl_test.py` | `data/session_ttl_report.json` | Холодный bookmark URL без cookies → пустая карточка; после `LIST_URL` шаблон `DETAIL_URL_TEMPLATE` стабилен |
| 2 | Маппинг `рег. номер → person_id` | `rosreestr_mapping_probe.py` | `data/mapping_probe_report.json` | `filterForm.regNum` + POST `person_list.do==` → `person_id` из `onEdit(N)` |
| 3 | Пагинация внутри карточки | `rosreestr_card_pagination_probe.py` | `data/card_pagination_probe.json` | **MONOLITH_FULL_TABLE** — все строки активности в первом GET, внутренней пагинации нет |
| 4 | Пустые секции DOM | `rosreestr_empty_sections_probe.py` | `data/empty_sections_probe.json` | «Данные не найдены» — без `<table>`; экстрактор возвращает `[]`, без падений |
| 5 | Формат CSV | `pytest tests/test_csv_format.py` | `data/csv_format_validation.json` | `utf-8-sig`, `;`, `QUOTE_ALL` — Excel и `COPY ... NULL ''` в PostgreSQL |

**Общий вывод:** один Playwright-воркер открывает список (`LIST_URL`), затем для каждой карточки подставляет `person_id` в `DETAIL_URL_TEMPLATE` и парсит полный HTML через BeautifulSoup. Отдельные клики по вкладкам, AJAX и внутренняя пагинация таблиц **не нужны**. Для CSV без `person_id` — фильтр по рег. номеру (~2–3 с на запись).

### Фаза 0: сетевой endpoint

Отдельного JSON/AJAX API для вкладки «Результаты профессиональной деятельности» **нет** — при клике новых `xhr`/`fetch` не появляется, таблица уже в HTML карточки (клиентский показ/скрытие).

| Назначение | Метод | URL |
|------------|-------|-----|
| Список реестра КИ | `GET` | `...QCB2freestr.do==/?reestr=9` |
| Карточка инженера | `GET` | `...QCB2fperson_view.do==/?id={person_id}&sroId=&excluded=false&filterName=personFilter` |

Ответ карточки: **`text/html; charset=UTF-8`** (не JSON). Прямой `GET` возможен через `playwright.request` после визита списка (cookies); голый запрос без сессии может отдать урезанную страницу.

```bash
# ContactFlow (Node)
cd parser/node_scripts
node rosreestr_probe.cjs --person-id 824174
node rosreestr_replay.cjs --person-id 824174

# GRKI (Python)
python rosreestr_network_probe.py --person-id 824174 --replay
```

### Фаза 1: TTL сессии / токена `!ut/p/z1/...`

```bash
python rosreestr_session_ttl_test.py
# отложенный прогон (30–60 мин): --save-only, затем повторный запуск
```

| Сценарий | activity rows | Вывод |
|----------|---------------|--------|
| Холодный сохранённый URL карточки | 0 | Нужны cookies контекста |
| `LIST_URL` → `DETAIL_URL_TEMPLATE` (тот же z1 из config) | 47 | Шаблон **не протух** за ~10+ мин |
| 5 карточек подряд после одного `LIST_URL` | 20–47 | Повторный прогрев list на каждую карточку **не нужен** |
| z1 в `LIST_URL` | без изменений | Стабилен между визитами |
| z1 через `editForm` | другой токен | Для конвейера используйте шаблон, не bookmark URL |

**Для прогона 37k:** в начале каждого воркера один `goto(LIST_URL)`; далее только подстановка `person_id` в `DETAIL_URL_TEMPLATE`. Раз в N карточек (или при `activityRows==0`) — повторный прогрев list.

### Фаза 2: маппинг рег. номер → person_id

```bash
python rosreestr_mapping_probe.py --reg-number 9624
```

| Способ | Работает | Примечание |
|--------|----------|------------|
| `filterForm.regNum` + `onFilter('set')` | Да | POST на `person_list.do==`, ответ — таблица |
| `extract_list_rows(html)` | Да | `person_id` из `onclick="onEdit(826933)"` |
| Заход в карточку | Не нужен | ID уже в HTML результатов |
| Поиск `824174` в regNum | Нет | 824174 — это `person_id`; рег. номер того же инженера — `23120` |

При частичных совпадениях (например, `9624` → также `19624`, `29624`) нужен exact match по колонке `reg_number`. Резерв: полная пагинация `setPage()`.

### Фаза 3: пагинация таблиц внутри карточки

```bash
python rosreestr_card_pagination_probe.py --person-id 824174
```

Проверены секции СРО, дисциплинарные воздействия и проф. деятельность на карточках с 46+ строками активности.

| Проверка | Результат |
|----------|-----------|
| `setPage()` / `sk_brdnav` внутри секций | Не найдены |
| XHR/fetch после загрузки карточки | Только метрика (Яндекс), не данные реестра |
| Строк в HTML vs извлечено экстрактором | Совпадают (~46) |

**Вердикт:** `MONOLITH_FULL_TABLE` — дополнительные клики и подгрузка страниц внутри карточки не требуются.

### Фаза 4: пустые и неполные секции

```bash
python rosreestr_empty_sections_probe.py
pytest tests/test_detail_extractor_empty_sections.py
```

| Кейс | person_id | Дисциплинарные | Активность |
|------|-----------|----------------|------------|
| Без дисциплинарных | 826933 | заголовок + «Данные не найдены», таблицы нет | ~47 строк (2014–2026) |
| Молодой инженер (2025) | 866551 | то же | 2 строки (2025–2026) |
| Эталон со всеми секциями | 824174 | таблица есть | ~47 строк |

Экстрактор корректно возвращает пустые списки, когда DOM содержит текст «Данные не найдены» вместо `<table>`. Фикстура `data/card_young_866551.html` используется в pytest.

### Фаза 5: формат CSV

```bash
python scripts/generate_csv_format_test.py
pytest tests/test_csv_format.py -v
```

Проверено на синтетических данных с точкой с запятой и кавычками внутри полей:

- кодировка `utf-8-sig` (BOM для Excel на Windows);
- разделитель `;`;
- `csv.QUOTE_ALL` — поля с `;` не ломают разбор;
- пустые значения → `""`, при импорте в PostgreSQL маппятся на `NULL` (`COPY ... NULL ''`).

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
