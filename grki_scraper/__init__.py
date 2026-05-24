"""
Пакет парсера ГРКИ (Росreestr).

Слои (снизу вверх):
  config          — настройки
  browser         — навигация Playwright
  extractors      — разбор HTML → dataclass (без I/O)
  writers         — запись результатов (CSV; заменяемый слой для PostgreSQL)
  checkpoint      — возобновление прогресса
  logger          — журнал ошибок

Оркестрация — в main.py (точка входа для CLI / Celery-задачи).
"""
