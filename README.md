# Альфа-Будущее / Signal

Новостная аналитика для руководителей: профиль и документы компании → события →
обоснованные риски и возможности → ситуации, сводка по роли и диалог с источниками.
React, Go API и Python analytics соединены в один стек.

- [Архитектура](docs/architecture.md)
- [Интеграция в main, запуск и результаты проверки](docs/integration-main-2026-10-24.md)
- [API backend](backend/API.md), [интерфейс Signal](frontend/FRONTEND_GUIDE_RU.md)
- [Аналитика](orchestrator/analytics/README.md), [спецификация](docs/analytics-spec-v1.md)
- [Парсер](parser_service/README.md), [деплой в k3s](docs/cd-k3s.md)
- [Графики из PDF: каталог, числовые данные и предпросмотр виджетов](docs/report-charts.md)
- [Самостоятельная проверка демки и загрузка тестовых профилей](docs/demo-profiles.md)
- [Подробная передача проекта агентам: история, архитектура, проверки и оставшиеся задачи](docs/agent-handoff-2026-10-25.md)

## Посмотреть интерфейс без API-ключа

Нужны Node 22+ и установленные зависимости (`cd frontend && npm ci`). Из корня:

```bash
make demo-web
```

Откройте <http://127.0.0.1:5173/login>, раскройте «Тестовые аккаунты» и выберите
профиль. Виджеты используют архивные графики из PDF; новости и ответы чата в этом
режиме подготовлены заранее, настройки сохраняются в браузере. Через «Добавить
виджет → График из PDF» можно выбрать отчёт и отдельный ряд.

Для проверки реальной LLM используйте полный стек ниже с `AI_API_KEY`. После
запуска `make demo-seed` (в Python venv) загрузит тестовые профили X5 и РЖД и восемь
документов через локальный API. [Порядок проверки и тестовые вопросы](docs/demo-profiles.md).

## Запуск приложения

Нужен Docker с Compose. Из корня репозитория:

```bash
cp .env.example .env
# В .env задайте AI_API_KEY и замените AI_SERVICE_TOKEN / INTERNAL_API_TOKEN.
make up
```

Откройте <http://localhost:8080>, зарегистрируйте компанию, пользователя и роли.
Загрузите документы в профиле компании; статус извлечения появится там же.
`make up` собирает оба образа, запускает PostgreSQL с pgvector, RustFS, Go API и
сборщик новостей, миграции, Python API и аналитический воркер. `make down`
останавливает сервисы, сохраняя тома. Без `AI_API_KEY` работают вход и чтение данных;
новая модельная обработка ждёт настройки ключа.

Миграции включают три RSS-источника: пресс-релизы Банка России, экономическую
ленту Интерфакса и Frank Media. Сборщик опрашивает их в этом порядке при старте
и затем каждые `INGEST_PERIOD` (по умолчанию 15 минут). Прежний широкий seed-набор
отключён для будущего сбора; сохранённые новости остаются.
[Выбор, приоритеты и ограничения источников](docs/news-sources.md).
Также доступен защищённый импорт `/api/v1/internal/news` из
[контракта backend](backend/API.md). Пустая лента означает отсутствие обработанных
новостей; приложение не подставляет демо.

Старым пользователям оператор назначает пароль через `cmd/set-password`;
[инструкция без пароля в истории shell](backend/API.md). Интеграция не меняет
пароли существующих аккаунтов автоматически.

## Разработка и проверки

Для процессов без контейнеров нужны Go из `backend/go.mod`, Node 22+, Python 3.12
и PostgreSQL с pgvector. `Makefile` экспортирует `.env`; активируйте Python venv
перед `make analytics-server` / `make analytics-worker`.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r orchestrator/analytics/requirements.txt -r parser_service/requirements-test.txt
docker compose up -d postgres rustfs
make analytics-migrate
# В разных терминалах, с активированным venv для Python:
make server
make web
make analytics-server
make analytics-worker
make worker
```

`make web` открывает Vite на :5173 и проксирует `/api` в Go. Не запускайте Go-сервер
одновременно с контейнером `server` на том же порту. Набор тестов с временными БД
и браузерами запускает `.github/workflows/pipeline-tests.yml`; сборку образов и
Helm проверяет `.github/workflows/ci-cd.yaml`.

Сквозная проверка с синтетической моделью, локальным S3-стендом и настоящими Go/Python HTTP:

```bash
UNIFIED_TEST_DATABASE_URL=postgresql://USER:PASSWORD@127.0.0.1:5432/analytics_test_unified \
  .venv/bin/python scripts/test_unified.py
```

Нужны права на создание временной БД и pgvector. Скрипт допускает только loopback
и имя `analytics_test_*`, создаёт дочернюю БД с уникальным именем и удаляет её в конце.
Реальные LLM и источники в тестах не вызываются.

## Где лежит код

| Каталог | Назначение |
|---|---|
| `frontend/` | Signal, вход, профиль, лента, ситуации, доказательства и чат |
| `backend/` | Сессии, компании, файлы S3, новости, очередь доставок, analytics proxy |
| `orchestrator/analytics/` | Документы, факты, retrieval, события, impacts/issues, snapshot/chat, API и worker |
| `orchestrator/` | Общие LLM-клиент, кеш, лимиты, typed-decision адаптер |
| `parser_service/` | Ограниченный сбор ЦБ, PostgreSQL jobs, проверяемый результат |
| `deploy/` | Helm, Argo CD и шаблон секретов |
| `docs/` | Спецификации, решения и отчёты |
