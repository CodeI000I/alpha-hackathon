# Signal — новостная аналитика для руководителей

Signal превращает внешние новости и корпоративный контекст в разборы рисков и
возможностей для конкретной компании и управленческой роли. Сервис объединяет
ленту событий, бизнес-ситуации с источниками, документы компании, аналитические
виджеты и ИИ-компаньона.

Проект подготовлен для кейса «Новостная аналитика для принятия бизнес-решений»,
направление корпоративно-инвестиционного бизнеса Альфа-Банка.

**Развёрнутый стенд:** [alpha.devgit.net](https://alpha.devgit.net) ·
[Вход](https://alpha.devgit.net/login) ·
[Регистрация](https://alpha.devgit.net/register).

**Github:** [Github](https://github.com/CodeI000I/alpha-hackathon)

**Для проверки проекта:** [инструкция по работе с сервисом](docs/demo-profiles.md).

## Содержание

- [Возможности и сценарий проверки](#product)
- [Тестовые пользователи](#demo-users)
- [Архитектура и поток данных](#architecture)
- [Логика аналитики и графы](#analytics)
- [Источники и предзагрузка](#sources)
- [Структура репозитория](#repository)
- [Запуск полного приложения](#launch)
- [Демонстрация без API-ключей](#offline-demo)
- [Конфигурация и Jev](#configuration)
- [Тестирование](#tests)
- [CI/CD и сервер](#deployment)
- [Документация](#documentation)

<a id="product"></a>
## Возможности и сценарий проверки

Пользователь задаёт профиль компании, выбирает управленческие роли и загружает
документы. Сервис связывает новости с доступными фактами: например, изменение
ставки может затрагивать стоимость долга, а событие в логистике — условия
закупок и непрерывность поставок.

| Возможность | Что доступно |
|---|---|
| Компании и роли | Регистрация, вход, профиль, документы и переключение назначенных ролей |
| Лента | Персональные карточки событий, рисков и возможностей, поиск, фильтры и закладки |
| Разбор | Связь новости с компанией, основания, источники и экспорт карточки в TXT |
| Бизнес-ситуации | Объединение связанных влияний, история версий и просмотр evidence |
| ИИ-компаньон | Вопросы к выбранной бизнес-ситуации с учётом её версии и оснований |
| Виджеты | Выбор графиков из подготовленных отчётов Альфа-Банка, исходные изображения и числовые ряды |
| Фоновая обработка | Новости, извлечение документов, очередь персонализации и пересчёт при изменении контекста |

Последовательность для демонстрации:

1. Откройте [стенд](https://alpha.devgit.net/login) и войдите в подготовленный аккаунт.
2. Проверьте компанию, роль и документы в личном кабинете.
3. На дашборде откройте событие и прочитайте его разбор и источники.
4. Откройте бизнес-ситуацию и спросите: «На какие данные нашей компании ты опираешься?».
5. Задайте уточнение: «Каких данных не хватает, чтобы принять решение?».
6. Добавьте график из PDF и сравните ряд с исходным фрагментом отчёта.
7. Перезагрузите страницу и проверьте сохранение состояния и истории диалога.

Чат работает в контексте выбранной бизнес-ситуации.
Подробный маршрут пользователя — в [инструкции](docs/demo-profiles.md).

<a id="demo-users"></a>
## Тестовые пользователи

На сервере подготовлены восемь тестовых пользователей в четырёх компаниях,
заполнены профили и загружены 16 документов.
Используйте реквизиты из таблицы на [странице входа](https://alpha.devgit.net/login).

Компания и документы общие для двух пользователей, роли и рабочие вопросы разные.
Профили, ИНН, документы и пароли — публичные синтетические данные
для демонстрационных сценариев.

| Компания | Пользователь | Роль | Логин | Пароль |
|---|---|---|---|---|
| Билайн | Дмитрий Тестовый | Стратегия — `strategy` | `dmitry.strategy@example.test` | `DemoStrategy2026!` |
| Билайн | Ирина Тестовая | Продукт — `product` | `irina.product@example.test` | `DemoProduct2026!` |
| X5 | Анна Тестовая | Финансы — `cfo` | `anna.finance@example.test` | `DemoFinance2026!` |
| X5 | Павел Тестовый | Коммерция — `commercial` | `pavel.commercial@example.test` | `DemoRetail2026!` |
| РЖД | Сергей Тестовый | Закупки — `procurement` | `sergey.procurement@example.test` | `DemoSupply2026!` |
| РЖД | Ольга Тестовая | Операции — `operations` | `olga.operations@example.test` | `DemoOperations2026!` |
| Группа «Эталон» | Марина Тестовая | Коммерция — `commercial` | `marina.commercial@example.test` | `DemoSales2026!` |
| Группа «Эталон» | Алексей Тестовый | Финансы — `cfo` | `alexey.finance@example.test` | `DemoDeveloper2026!` |

Для воспроизведения набора в своём окружении используйте
[инструкцию подготовки](docs/demo-profiles.md#server-accounts).
Состав профилей, документов и ролевые сценарии:
[fixtures/miro-personas](fixtures/miro-personas/README.md).

<a id="architecture"></a>
## Архитектура и поток данных

Основной стек: **React + TypeScript → Go → Python / LangGraph → PostgreSQL / pgvector**.
Оригиналы документов хранятся в S3-совместимом RustFS. Go и frontend поставляются
одним образом, Python analytics — вторым.

```mermaid
flowchart LR
    Browser["Браузер: Signal / React"] -->|"HTTPS, cookie-сессия"| Go["Go API + frontend"]
    Go --> PG[("PostgreSQL + pgvector")]
    Go --> S3[("RustFS / S3")]
    Go -->|"Проверенный scope и service token"| API["Python analytics API"]
    RSS["ЦБ / Интерфакс / Frank Media"] --> GW["Go worker"]
    Seed["Архивный снимок за 21 день"] --> PG
    GW -->|"Новости и очередь доставок"| PG
    GW -->|"POST /rank"| API
    PW["Python analytics worker"] -->|"Профили и метаданные файлов"| PG
    PW -->|"Получение оригиналов"| Go
    API --> Engine["AnalyticsService / LangGraph"]
    PW --> Engine
    Engine --> PG
    Engine --> LLM["Модельный шлюз"]
    Engine -.->|"Опциональный триаж"| Jev["Jev / System One"]
```

| Компонента | Назначение | Точка входа |
|---|---|---|
| Go API | Сессии, компании, профили, файлы, лента и проксирование аналитики | [backend/cmd/server](backend/cmd/server/main.go) |
| Go worker | RSS, сохранение ревизий, очередь `news_deliveries`, обращение к `/rank` | [backend/cmd/worker](backend/cmd/worker/main.go) |
| Python API | Закрытый `/rank` и `/v1/analytics`: ситуации, evidence, история и чат | [orchestrator/analytics/app.py](orchestrator/analytics/app.py) |
| Python worker | Документы, синхронизация профиля, аналитические задания и пересчёт | [orchestrator/analytics/worker.py](orchestrator/analytics/worker.py) |
| PostgreSQL | Пользователи, новости, очереди и версионированные результаты аналитики | [backend/migrations](backend/migrations), [analytics/migrations](orchestrator/analytics/migrations) |
| RustFS | Оригиналы загруженных документов | [docker-compose.yml](docker-compose.yml) |
| Отдельный парсер | Ограниченный сбор ЦБ и проверяемые результаты; опциональный путь | [parser_service](parser_service/README.md) |

Браузер обращается к одному origin. Go проверяет сессию, компанию и роль и сам
передаёт scope аналитике. Ключи внешних моделей и внутренние токены не передаются
в браузер. Пароли хешируются bcrypt; сессия хранится в HttpOnly cookie.

Подробности согласованности, изоляции данных, lease/fencing и повторов:
[архитектура](docs/architecture.md) и [ADR единого контура](docs/decisions/0001-unified-runtime.md).

<a id="analytics"></a>
## Логика аналитики и графы

### От новости до персонального результата

1. **Получение.** RSS-сборщик сохраняет источник, исходный ID, URL, дату,
   заголовок и доступный текст. Повторное получение не создаёт новую запись;
   изменение содержания увеличивает ревизию.
2. **Корпоративные знания.** Профиль и документы дают чанки, факты и связи.
   Значения формы сохраняются как пользовательские утверждения. Для подтверждения
   документом нужны существующий фрагмент и цитата.
3. **Событие.** Аналитика нормализует новость в общее событие, затем рассматривает
   его влияние отдельно для каждой компании.
4. **Retrieval.** Собираются относящиеся к событию факты компании, фрагменты
   документов и связи. По умолчанию используется лексический режим; локальные
   embeddings и импорт Graphify включаются отдельно.
5. **Assessment.** Модель формирует структурированную оценку влияния с основаниями.
   Недостаток evidence, ошибки модели и невалидный ответ не считаются успешным анализом.
6. **Ситуация.** Принятые влияния объединяются в версионные `BusinessIssue`;
   готовится `SituationSnapshot` по роли. Чтение готовых результатов не вызывает LLM.
7. **Диалог.** Вопрос относится к выбранной версии ситуации. История старой версии
   сохраняется; переход к новой версии диалога выполняется явно.

В [AnalyticsService](orchestrator/analytics/service.py) фактический LangGraph
оценки имеет четыре узла:

```mermaid
flowchart TD
    Start(["START"]) --> Retrieve["retrieve: evidence и проверка кеша"]
    Retrieve -->|"Актуальный результат в кеше"| Finish(["END"])
    Retrieve -->|"Нужен новый анализ"| Triage["triage: опциональная подсказка Jev / LLM"]
    Triage --> Assess["assess: обоснованная оценка влияния"]
    Assess --> Save["save: результат и маршрут обработки"]
    Save --> Finish
```

**Jev выполняет дополнительный триаж:** возвращает `relevance`, `kind` и
`priority`. При включении его решение передаётся в assessment как предварительная
подсказка; итоговая оценка строится по evidence. Этап управляется переменной
`ANALYTICS_TRIAGE_ENABLED`.

### Связи данных и версий

Логическая схема объектов показывает, как разбор связан с источниками
и как изменения контекста связаны с пересчётом.

```mermaid
flowchart LR
    Company["Компания"] --> Profile["Профиль и документы"]
    Profile --> Facts["Факты и связи компании"]
    News["Новость + источник + ревизия"] --> Event["Нормализованное событие"]
    Facts --> Evidence["EvidencePack"]
    Event --> Evidence
    Evidence --> Impact["CompanyImpact"]
    Impact --> Issue["BusinessIssue + версия"]
    Issue --> Snapshot["SituationSnapshot по роли"]
    Issue --> Chat["Диалог на выбранной версии"]
    Evidence --> Chat
```

Рабочий граф знаний хранится в аналитическом контуре. Служебный индекс Graphify
используется для навигации по документации проекта.
[Спецификация аналитики](docs/analytics-spec-v1.md).

<a id="sources"></a>
## Источники и предзагрузка

| Источник | Автоматический сбор | Содержание |
|---|---|---|
| Банк России, S077 | RSS пресс-релизов | Заголовок, описание, ссылка и дата |
| Интерфакс, S136 | RSS, категория «Экономика» | Заголовок, анонс, ссылка и дата |
| Frank Media, S142 | RSS | Описание и полный текст, если издатель передал его в RSS |

Сбор выполняется сразу при старте Go worker, затем каждые **15 минут**
(`INGEST_PERIOD`). При отказе одного источника остальные продолжают обрабатываться.
Состав реально включённых источников определяется таблицей `sources` в БД.
[Описание источников](docs/news-sources.md).

**Cold start:** в образ включён снимок **352 реальных публикаций за 5–26 октября
2026 года**: 11 ЦБ и 341 Frank Media. При старте backend снимок однократно
записывается существующим механизмом миграций с сохранением исходных дат
и более свежих версий материалов.

После регистрации или изменения профиля/ролей очередь охватывает последние
**21 день** (`RANK_LOOKBACK=504h`). Общий корпус служит основой персонализации
по профилю компании и роли. Скорость обработки зависит от очереди и доступности LLM;
`RANK_MAX_PER_RUN=20` ограничивает оценки за проход. [Подробности cold start](docs/news-coldstart.md).

**Материалы Альфа-Банка:** подготовлен статический набор из 9 PDF: 97 диаграмм,
253 отдельных ряда данных. Для 234 рядов доступны SVG; точные подписи отделены
от приблизительной оцифровки. Эти материалы используются в виджетах.
[Каталог, форматы и метод оцифровки](docs/report-charts.md).

<a id="repository"></a>
## Структура репозитория

```text
.
├── frontend/                       # React / TypeScript / Vite
│   ├── src/
│   │   ├── pages/                  # Вход, регистрация, дашборд, профиль, ситуации
│   │   ├── components/             # Общие компоненты и графики
│   │   ├── api/                    # Типы, HTTP-клиент, автономное демо
│   │   └── signal/                 # Элементы интерфейса Signal
│   ├── public/report-charts/       # Каталог PDF-графиков, изображения, JSON / SVG
│   └── tests/                      # Vitest и Playwright
├── backend/                        # Go API и сборщик
│   ├── cmd/{server,worker}/        # Основные процессы
│   ├── cmd/set-password/           # Операторское назначение пароля
│   ├── internal/
│   │   ├── httpapi/                # Сессии, onboarding, API, analytics proxy
│   │   ├── ingest/                 # RSS, доставка, retry/backoff
│   │   ├── storage/                # PostgreSQL и S3
│   │   ├── feed/                   # Контракт ранжирования и ленты
│   │   └── orchestrator/           # HTTP-клиент Python analytics
│   ├── migrations/                # Схема, справочники и RSS-конфигурация
│   └── coldstart/                 # Встроенный снимок новостей и manifest
├── orchestrator/                   # Общие настройки и LLM-инфраструктура
│   ├── config.py, llm.py           # Разрешённые модели, клиент, лимиты и кеш
│   ├── decision.py                # Адаптер Jev / Clef и fallback
│   ├── analytics/
│   │   ├── app.py, router.py       # Закрытый HTTP API
│   │   ├── integration.py          # Совместимость с контрактом Go /rank
│   │   ├── service.py              # LangGraph и обработка влияния
│   │   ├── knowledge.py            # Документы, факты, retrieval
│   │   ├── models.py, store.py     # Типы и версионированное хранение
│   │   ├── synthesis.py, worker.py # Сводки и фоновые задания
│   │   ├── migrations/            # Аналитическая схема PostgreSQL
│   │   └── tests/                 # Проверки аналитического контура
│   └── tests/                     # LLM-клиент, маршрутизация, общая логика
├── parser_service/                 # Ограниченный парсер ЦБ, jobs, HTTP-контракт
├── fixtures/miro-personas/          # 4 синтетические компании, 8 пользователей
├── scripts/                        # Загрузчик профилей, подготовка снимка и графиков
├── experiments/                    # Notebook с экспериментами и протоколами запусков
├── eda/                            # Анализ PDF и разметка графиков
├── docs/                           # Архитектура, инструкции, спецификации, ADR
├── deploy/helm/alpha-hackaton/      # Kubernetes / k3s Helm-чарт
├── deploy/argocd/                  # GitOps-приложение Argo CD
├── .github/workflows/              # Тесты, сборка образов и CI/CD
├── company_research.xlsx           # Исходный каталог профиля, ролей и источников
├── Dockerfile                      # Go + собранный frontend
├── Dockerfile.analytics            # Python analytics + OCR
├── docker-compose.yml              # Полный локальный стек
├── .env.example                    # Переменные без рабочих секретов
└── Makefile                        # Команды запуска и разработки
```

В репозитории хранятся код, подготовленные демонстрационные данные и протоколы
экспериментов. Рабочие секреты и локальные выгрузки размещаются отдельно.

<a id="launch"></a>
## Запуск полного приложения

### 1. Требования

- Git, Docker Engine / Desktop с Docker Compose v2; команда `make` для сокращённых команд.
- Доступ к Docker Hub, npm, Python-пакетам и ресурсам подготовки OCR при первой сборке.
- Ключ модельного шлюза организаторов для новых модельных разборов.
- Для загрузчика тестовых профилей: Python 3.12 и зависимости проекта.

В контейнерах используются Node 22, Go версии из [go.mod](backend/go.mod),
Python 3.12, PostgreSQL 16 с pgvector и RustFS. Для Docker-запуска не требуется
устанавливать Go, Node и Python на хост отдельно.

### 2. Настройка

```bash
git clone https://github.com/CodeI000I/alpha-hackathon.git
cd alpha-hackathon
cp .env.example .env
```

В локальном `.env` заполните:

```dotenv
AI_API_KEY=<ключ модельного шлюза организаторов>
AI_SERVICE_TOKEN=<случайный внутренний токен>
INTERNAL_API_TOKEN=<другой случайный внутренний токен>
```

Два независимых значения токенов можно получить отдельными вызовами
`openssl rand -hex 32`. Для собственного окружения также задайте пароли PostgreSQL
и RustFS. `AI_API_KEY` — ключ аналитической LLM; ключ Jev задаётся отдельно.
Compose читает настройки из `.env`; прямой Python-запуск — из `.env.local`.
Файлы с рабочими секретами исключены из Git и Docker build context.

### 3. Сборка и старт

```bash
make up
# Эквивалент: docker compose up --build -d

docker compose ps
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/readyz
```

Первый запуск собирает frontend и Python-образ, подготавливает OCR, создаёт БД и
применяет миграции. `analytics-migrate` — одноразовый процесс; успешное завершение
этого контейнера нормально. Откройте [http://localhost:8080](http://localhost:8080).
Порты хоста 5432, 8080, 9000 и 9001 должны быть свободны.

| Сервис | Адрес / доступ |
|---|---|
| Приложение и Go API | `http://localhost:8080` |
| PostgreSQL | `127.0.0.1:5432` |
| RustFS S3 / console | `127.0.0.1:9000` / `127.0.0.1:9001` |
| Python analytics API | Внутри Compose: `http://analytics:8090` |

Health endpoint показывает работу процесса, readiness Go — доступность его БД.

### 4. Пользователи и работа

Можно зарегистрировать свою тестовую компанию через UI или загрузить готовые профили:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r orchestrator/analytics/requirements.txt
.venv/bin/python scripts/seed_demo_profiles.py \
  --base-url http://127.0.0.1:8080 --personas beeline x5 rzd etalon
```

Загрузчик создаёт первых пользователей, записывает профили и загружает четыре
документа каждой компании через API. Используйте отдельную демонстрационную БД.
Коллеги создаются отдельно по [инструкции](docs/demo-profiles.md#server-accounts).
Дождитесь статуса документов «Анализ завершён», затем проверяйте ленту и ситуации.
Без `AI_API_KEY` вход и чтение работают, новая модельная обработка ожидает настройки.

### 5. Логи и остановка

```bash
docker compose logs --tail=100 server worker analytics analytics-worker
make down
# Эквивалент: docker compose down — тома с данными сохраняются.
```

Для разработки отдельными процессами, Vite proxy и подготовки тестовых БД:
[подробная инструкция](docs/demo-profiles.md#development).

<a id="offline-demo"></a>
## Демонстрация без API-ключей

Этот режим подходит для просмотра интерфейса без backend, PostgreSQL и LLM:

```bash
cd frontend
npm ci
cd ..
make demo-web
```

Откройте [http://127.0.0.1:5173/login](http://127.0.0.1:5173/login) и раздел
«Тестовые аккаунты».

| Сценарий | Логин | Пароль |
|---|---|---|
| Финансы и стратегия | `finance@signal.demo` | `SignalDemo2026!` |
| Операции промышленной компании | `operations@signal.demo` | `SignalDemo2026!` |

Эти два аккаунта относятся к автономному браузерному демо. Лента и ответы
подготовлены заранее, настройки сохраняются в браузере, PDF-графики взяты из
архивного набора. Production frontend по умолчанию использует API. Режим
задаётся при сборке через `VITE_DATA_MODE`.

<a id="configuration"></a>
## Конфигурация и Jev

Полный список переменных: [.env.example](.env.example).

| Переменная | Назначение / значение по умолчанию |
|---|---|
| `AI_API_KEY` | Ключ аналитического модельного шлюза |
| `AI_DEFAULT_MODEL`, `AI_*_MODEL` | Модель по умолчанию и переопределения этапов; допустимые ID — в `orchestrator/config.py` |
| `AI_SERVICE_TOKEN` | Авторизация Go → Python; Compose передаёт его как `ORCHESTRATOR_TOKEN` в Go |
| `INTERNAL_API_TOKEN` | Закрытый импорт новостей и скачивание оригиналов документов |
| `INGEST_PERIOD` | Интервал RSS: `15m` |
| `RANK_LOOKBACK` | Окно оценки: `504h` |
| `RANK_MAX_PER_RUN` | Максимум оценок за проход: `20` |
| `NEWS_COLDSTART_ENABLED` | Загрузка встроенного архива: `true` |
| `ANALYTICS_POLL_SECONDS` | Интервал аналитического worker: `5` секунд |
| `ANALYTICS_TRIAGE_ENABLED` | Предварительный триаж Jev / fallback: `false` |
| `EMBEDDING_BACKEND` | `lexical`; `local` требует подготовленной локальной модели |
| `ANALYTICS_GRAPHIFY_ENABLED` | Импорт подготовленного Graphify JSON: `false` |

Для локального Jev дополнительно задаются `AI_SYSTEMONE_URL`,
`AI_SYSTEMONE_MODEL=jev-latest`, `AI_SYSTEMONE_API_KEY` и
`ANALYTICS_TRIAGE_ENABLED=true`. В Docker Compose их читают **`analytics` и
`analytics-worker`**. При прямом Python-запуске используется
`.env.local`. Проверка доступности модели:

```bash
.venv/bin/python -m orchestrator check-systemone
```

Команда проверяет доступность модели через `/v1/models`.
[Протокол live smoke](experiments/jev_live_check_2026-10-26.ipynb) ·
[Настройка адаптера Jev](orchestrator/README.md).

<a id="tests"></a>
## Тестирование

| Уровень | Что проверяется |
|---|---|
| Go | API, сессии, изоляция компаний, RSS, очереди и повторная доставка |
| Python | Схемы, evidence, retrieval, LangGraph, кеш, версии, parser и Jev/fallback |
| Frontend | Компоненты и преобразования данных через Vitest; пользовательские сценарии через Playwright |
| Сквозной smoke | Настоящие Go/Python HTTP и PostgreSQL с синтетическими LLM/S3-адаптерами |
| Подготовленные данные | Контрольные суммы cold start, схема/окно RSS, PDF-графики и числовые ряды |

Команды базовых проверок:

```bash
# PostgreSQL integration tests требуют отдельных тестовых DSN; без них часть Go/Python тестов пропускается.
(cd backend && go test -race ./... -count=1 && go vet ./...)
.venv/bin/python -m unittest discover -s orchestrator/tests -q
.venv/bin/python -m unittest discover -s orchestrator/analytics/tests -q
.venv/bin/python -m unittest discover -s parser_service/tests -q
.venv/bin/python -m unittest scripts.test_prepare_news_coldstart -v
(cd frontend && npm ci && npm run test && npm run typecheck)
(cd frontend && npx playwright install chromium && npm run test:e2e)
```

Настройка PostgreSQL, OCR и окружения без пропусков зафиксирована в
[Pipeline tests](.github/workflows/pipeline-tests.yml). Для сквозного smoke нужны
зависимости Python/Go, pgvector и отдельная loopback-БД с правом создавать дочернюю БД:

```bash
UNIFIED_TEST_DATABASE_URL=postgresql://USER:PASSWORD@127.0.0.1:5432/analytics_test_unified \
  .venv/bin/python scripts/test_unified.py
```

На 26 октября 2026 в срезе cold start подтверждены **128 Go-тестов/подслучаев с
race detector без пропусков**, `go vet`, 4 Python-проверки снимка и unified smoke.
Smoke включает 6 синтетических модельных вызовов.
[Протокол запуска](experiments/coldstart_2026-10-26.ipynb).

Отдельно Jev принял три реальных тестовых запроса без fallback; 28 unit-тестов
адаптера и 2 проверки demo triage прошли.
[Протокол Jev](experiments/jev_live_check_2026-10-26.ipynb).

<a id="deployment"></a>
## CI/CD и сервер

Развёртывание описано для **k3s + Helm + Argo CD**, namespace `alpha`.
Публичный ingress — [alpha.devgit.net](https://alpha.devgit.net); Python API остаётся
внутренним сервисом. Секреты создаются отдельно от Git по
[шаблону](deploy/secrets.example.yaml).

```mermaid
flowchart LR
    Code["Изменения main"] --> Tests["Pipeline tests + Go / frontend / Helm проверки"]
    Tests --> Images["Сборка и публикация двух образов"]
    Images --> Tags["Коммит тегов образов в Helm values"]
    Tags --> Argo["Argo CD синхронизирует main"]
    Argo --> Cluster["k3s: Go, analytics, PostgreSQL, RustFS"]
```

Основной workflow: [ci-cd.yaml](.github/workflows/ci-cd.yaml).
Полный pipeline проверок: [pipeline-tests.yml](.github/workflows/pipeline-tests.yml).
Статус тестов и сборки доступен в GitHub Actions, синхронизация и здоровье
приложения — в Argo CD.

Полная установка, HTTPS, secrets и эксплуатация: [docs/cd-k3s.md](docs/cd-k3s.md).
Подготовка собственного стенда: [инструкция демонстратора](docs/demo-profiles.md#server-accounts).

<a id="documentation"></a>
## Документация

| Материал | Содержание |
|---|---|
| [Инструкция демонстратора](docs/demo-profiles.md) | Вход, подготовка пользователей, профили, документы, сценарии и диагностика |
| [Frontend guide](frontend/FRONTEND_GUIDE_RU.md) | Экраны, роли, состояния и границы автономного демо |
| [Backend API](backend/API.md) | HTTP-контракты и авторизация |
| [Архитектура](docs/architecture.md) | Компоненты, хранение, доступ и согласованность |
| [Analytics README](orchestrator/analytics/README.md) | Аналитический runtime, документы, retrieval и команды |
| [Спецификация](docs/analytics-spec-v1.md) | Подробная модель объектов и алгоритмов |
| [Источники](docs/news-sources.md) / [cold start](docs/news-coldstart.md) | RSS и перенос архивного снимка |
| [PDF-графики](docs/report-charts.md) | Каталог, оцифровка, точность и проверка данных |
| [Тестовые профили](fixtures/miro-personas/README.md) | Восемь пользователей и синтетические документы |
| [Парсер](parser_service/README.md) | SourcePolicy, jobs и проверка evidence |
| [Деплой](docs/cd-k3s.md) | k3s, Helm, Argo CD и HTTPS |
