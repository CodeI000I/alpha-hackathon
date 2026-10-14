# alpha-hackaton
Repository for alpha-future hackaton on course "News analytics for business decision-making"

Сервис персональной новостной аналитики для руководителей крупного бизнеса: Go backend, React frontend, k3s.

* Архитектура: [docs/architecture.md](docs/architecture.md)
* Деплой в k3s и CI: [docs/cd-k3s.md](docs/cd-k3s.md)

## Что где лежит

```
.
├── Dockerfile               сборка одного образа: фронтенд + два Go-бинарника (server, worker)
├── docker-compose.yml       Postgres и RustFS (S3) для локальной разработки
├── Makefile                 make up / server / worker / web / build / seed
├── .env.example             переменные окружения (скопировать в .env)
├── backend/                 Go-модуль
│   ├── cmd/server/main.go   точка входа API: читает конфиг, применяет миграции, слушает :8080
│   ├── cmd/worker/main.go   точка входа воркера: по таймеру собирает новости и строит ленты
│   ├── internal/config/     настройки из переменных окружения
│   ├── internal/domain/     структуры, которые уходят во фронтенд как JSON
│   ├── internal/httpapi/    маршруты /api/v1/* и обработчики, раздача собранного фронтенда
│   ├── internal/storage/postgres/  SQL-запросы: пользователи и роли, компании, новости, лента
│   ├── internal/storage/files/     загрузка файлов компаний в S3 (RustFS)
│   ├── internal/ingest/     сбор новостей: общий конвейер + адаптеры (rss.go, alfa.go)
│   ├── internal/feed/       решение «что в ленту»: клиент Jev + заглушка по ключевым словам
│   └── migrations/          0001_init.sql — схема БД, 0002_seed.sql — справочники из xlsx
├── frontend/                React + Vite + TypeScript
│   └── src/
│       ├── api/             типы и fetch-клиент для backend
│       ├── pages/           Onboarding (компания и роли), Feed (лента по ролям), Company (профиль, файлы)
│       └── components/      RolePicker — выбор нескольких ролей
├── deploy/
│   ├── k8s/                 манифесты k3s: namespace, postgres, rustfs, app + worker, ingress (kustomize)
│   └── ci/                  раннер GitHub Actions в кластере: helm values, RBAC, пример workflow
├── docs/
│   ├── architecture.md      компоненты, модель данных, API, контракт с Jev
│   └── cd-k3s.md            варианты деплоя в k3s и пошаговая установка раннера
└── scripts/gen_seed.py      company_research.xlsx → backend/migrations/0002_seed.sql
```

## Локальный запуск

```bash
cp .env.example .env
make up        # Postgres + RustFS в docker compose
make server    # API на :8080, миграции применяются сами
make web       # фронтенд на :5173
make worker    # по желанию: сбор новостей
```

Нужны Go 1.23+, Node 20+, Docker.
