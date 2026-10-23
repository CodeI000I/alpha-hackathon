# Аналитический прототип «Альфа-Будущее»

Изолированный модуль поверх существующего `orchestrator`: документы → знания компании,
общий архив новостей → события → CompanyImpact → BusinessIssue → SituationSnapshot.
Чтение готовой сводки, источников, истории и переписки не вызывает LLM.
Спецификация: [analytics-spec-v1.md](../../docs/analytics-spec-v1.md).
Результаты проверки: [analytics-prototype-report.md](../../docs/analytics-prototype-report.md).
Полный аудит и последние проверки: [pipeline-audit-2026-10-23.md](../../docs/pipeline-audit-2026-10-23.md).

`router.py` создаёт **незарегистрированный** APIRouter. Он не импортируется приложениями
backend/frontend или существующим `orchestrator.api`. HTTP проверяется только через
временный FastAPI/TestClient. В проект не добавлены фоновые службы или сетевой listener.

## Быстрый запуск без API и PostgreSQL

Из корня репозитория, Python 3.12:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r orchestrator/analytics/requirements.txt
.venv/bin/python -m orchestrator.analytics demo
```

Демо использует настоящий `LLMClient` и `httpx.MockTransport`: HTTP-ответы заданы
синтетическими фикстурами, ключ не нужен, сетевых модельных вызовов нет. Договор,
морская логистика, курс валюты и новый прайс дают три события и одну ситуацию со
смешанным эффектом. Вопрос пользователя не меняет факты. Новая версия договора
запускает пересчёт. В JSON проверяются `events=3`, `issues=1`, `read_calls=0` и
`after.current=true`. Оригиналы демо лежат во временном каталоге и удаляются после него.

## Изолированная PostgreSQL

Нужны отдельная тестовая база PostgreSQL с установленным pgvector и пользователь,
имеющий право создавать extension/schema. Проверено с PostgreSQL 17 и pgvector 0.8.7.
Схема `analytics` и таблицы checkpoints создаются только явной миграцией.
`ANALYTICS_DATABASE_URL` обязателен; `DATABASE_URL` backend не используется.

```bash
export ANALYTICS_DATABASE_URL='postgresql://USER@127.0.0.1:PORT/analytics_test_prototype'
.venv/bin/python -m orchestrator.analytics migrate
.venv/bin/python -m orchestrator.analytics demo --postgres-test-dsn "$ANALYTICS_DATABASE_URL"
```

Базу нужно предварительно создать. Демо принимает только loopback и имя
`analytics_test_*`, создаёт новый tenant при каждом запуске, не удаляет историю
предыдущих запусков. Модель по-прежнему синтетическая; persistence и PostgresSaver настоящие.
Не указывайте рабочую БД для тестов: они создают схемы, записи и checkpoints.

## Рабочие операции сервиса

Настройки читаются из `.env.local` и переменных процесса. Процесс имеет приоритет.
Существующий `.env.local` не заменяйте. Все параметры перечислены в `.env.example`.
Модельный адаптер переиспользован из `orchestrator.llm`: Chat Completions, JSON/Pydantic,
ограниченные retries, timeout/RPM, cache, сохранение budget block до сброса шлюза.

Следующие операции, кроме чтения и постановки refresh, могут вызвать настроенный
модельный API. В разработке они проверены через подставной transport.

```bash
# CompanyProfile JSON; tenant/company задаются отдельно доверенным вызывающим кодом.
.venv/bin/python -m orchestrator.analytics profile --tenant demo --company plant --file company.json
.venv/bin/python -m orchestrator.analytics document --tenant demo --company plant --id contract --revision 1 --file contract.pdf
.venv/bin/python -m orchestrator.analytics news --tenant demo --company plant --file news.json
# refresh только ставит задание; явный CLI refresh разрешает повтор failed-задания.
.venv/bin/python -m orchestrator.analytics refresh --tenant demo --company plant
.venv/bin/python -m orchestrator.analytics worker --tenant demo --company plant
# Один периодический проход, без установки фоновой службы.
.venv/bin/python -m orchestrator.analytics schedule --tenant demo --company plant
.venv/bin/python -m orchestrator.analytics situation --tenant demo --company plant
.venv/bin/python -m orchestrator.analytics issues --tenant demo --company plant
.venv/bin/python -m orchestrator.analytics evidence --tenant demo --company plant --id ISSUE_ID
.venv/bin/python -m orchestrator.analytics history --tenant demo --company plant --id ISSUE_ID
.venv/bin/python -m orchestrator.analytics ask --tenant demo --company plant --user alice --id ISSUE_ID --conversation c1 --request-id q1 --question 'Что если цена фиксирована?'
.venv/bin/python -m orchestrator.analytics conversation --tenant demo --company plant --user alice --id c1
.venv/bin/python -m orchestrator.analytics state --tenant demo --company plant --user alice --id ISSUE_ID
.venv/bin/python -m orchestrator.analytics metrics --tenant demo --company plant
```

Минимальный `company.json`:

```json
{"name":"Завод","facts":[{"fact_id":"contract-1","text":"Закупки у supplier-x по плавающей цене","subject_id":"plant","predicate":"buys_from","object_id":"supplier-x","exposure":"november-order","business_factors":["procurement_cost"],"verification_status":"user_asserted"}]}
```

Минимальный `news.json`:

```json
{"source":"alfabank","news_id":"n-1","revision":1,"title":"Поставщик изменил прайс","content":"supplier-x объявил повышение цены комплектующих с ноября.","published_at":"2026-10-23T09:00:00Z","upstream_validated":true}
```

`user_asserted` сохраняет авторство пользователя, а `source_supported` требует реальную
цитату и существующий chunk этой компании. Одинаковая ревизия с другим содержимым
отклоняется. Изменение профиля/документа ставит пересчёт существующего архива в очередь.
Задания имеют lease и ограничение попыток; budget pause попытку не расходует.
Чтение возвращает `current=false`, если изменились источники, знания, политика либо
временная применимость. Оно само не запускает пересчёт.

## Документы, embeddings и Graphify

TXT/Markdown, HTML (существующий `parser_service.html_document.clean_html`), PDF
(текст и OCR), DOCX (абзацы, таблицы, headers/footers) сохраняют точные locators.
Оригиналы записываются атомарно в `ANALYTICS_OBJECT_DIR`; имена файлов пользователя
не используются как пути. Неуспешное извлечение оставляет исходник и статус ошибки.
Знания и готовая ревизия документа публикуются одной транзакцией.

OCR требует локальные `eng.traineddata` и `rus.traineddata`. Подготовка ресурсов
выполняется только явно; runtime ничего не скачивает:

```bash
.venv/bin/python -m orchestrator.analytics.prepare_assets --ocr
.venv/bin/python -m pip install -r orchestrator/analytics/requirements-embeddings.txt
.venv/bin/python -m orchestrator.analytics.prepare_assets --model
export EMBEDDING_BACKEND=local
export EMBEDDING_MODEL_PATH=orchestrator/data/embedding-model
```

OCR assets проверяются по SHA-256; модель закреплена на commit
`e8f8c211226b894fcb81acc59f3b34ba3efd5f42`. Для OCR можно переопределить `TESSDATA_PREFIX`;
по умолчанию используется `orchestrator/data/tessdata`. Эти ресурсы игнорируются Git.
Без них обычный текстовый PDF работает, скан явно возвращает `OCR_LANG_DATA_MISSING`.
Смешанные страницы проходят partial OCR с сохранением native-текста; страницы без
извлекаемого текста — full OCR, включая векторную отрисовку букв. До растеризации
проверяются лимиты 25 млн пикселей на страницу и 200 млн на документ при 300 DPI.
При передаче `original` документ должен происходить из `parse_document`: SHA-256
исходных байтов и разобранного текста проверяются перед записью.
Проверяются также offsets, текст, hash и идентификаторы chunks. Лимиты текста
проверяются по ходу разбора PDF/DOCX и повторно на границе прямого `ingest`.
Лексический режим — полноценный baseline с BM25, PostgreSQL FTS и типизированными путями.
При включении embeddings новые документы индексируются векторами с версией текста,
моделью и её версией. Для старого корпуса доступен явный Python API:

```python
# service настроен с локальными embeddings, scope взят из доверенного контекста.
indexed = service.knowledge.reindex(scope)
job = service.reprocess_company(scope, reason='embedding-reindex')
```

Reindex атомарно обновляет индекс текущих ready chunks и фактов, без LLM-вызовов,
повторного extraction и изменения исходных ревизий. Job лишь ставит отдельный
пересчёт оценок в очередь; автоматическая массовая переиндексация не запускается.
Длинный текст разбивается по реальному tokenizer/max_seq_length локальной модели;
векторы окон агрегируются с весами по числу токенов. Версия теперь имеет суффикс
`:token-windows-v1`: прежние усечённые векторы с ней несовместимы. До переиндексации
таких документов доступны лексические каналы. Это устраняет тихое усечение хвоста,
но увеличивает стоимость локального encode; замеры приведены в отчёте аудита.

Перед assessment проверяется полный размер запроса с JSON, инструкцией и схемой.
Если evidence не помещается в `AI_MAX_INPUT_CHARS`, сохраняется `needs_context`
с причиной `context_limit`, а модель не вызывается. Все факты/оговорки остаются
в сохранённом evidence. Необязательный preliminary triage можно опустить, чтобы
он не вытеснял первичные основания. Extraction крупных документов по-прежнему
ограничен настройками LLM; лимит парсера не обещает, что весь текст помещается в модель.

Graphify выключен по умолчанию. Для импорта подготовленного JSON текущего документа:

```bash
export ANALYTICS_GRAPHIFY_ENABLED=true
export ANALYTICS_GRAPHIFY_JSON_PATH=/absolute/path/contract-graph.json
```

Формат — `{"extractor_version":"...","edges":[...]}`; каждое ребро содержит
`subject_id`, `predicate`, `object_id`, `evidence_refs` (chunk IDs текущей ревизии)
и буквальную `source_quote`. Разрешённые типы находятся в `knowledge.ALLOWED_RELATIONS`.
Чужие/несуществующие refs, неподтверждённые даты и неподдерживаемые связи отклоняются.
Этот путь выбирается для конкретного документа; перед следующим документом/ревизией
нужно указать соответствующий JSON либо выключить импорт. Graphify не запускается
прототипом и не получает корпоративные данные автоматически.

## Предварительный триаж System One

Добавленный командой `orchestrator.decision.DecisionRouter` подключён к LangGraph
после retrieval и проверки кеша. Включение явное:

```dotenv
ANALYTICS_TRIAGE_ENABLED=true
AI_SYSTEMONE_URL=https://api.typesafe.ai
AI_SYSTEMONE_MODEL=jev-latest
AI_SYSTEMONE_API_KEY=<отдельный ключ TypeSafe>
```

Одного `AI_SYSTEMONE_URL` недостаточно для включения. При пустом URL используется
существующий LLMClient; его ключ нужен и для полного анализа. Ключи в Git не сохраняются.
После включения рабочие команды анализа передают выбранный корпоративный контекст
настроенному провайдеру. Read-only команды создают только идентификатор политики,
не создают HTTP-клиент и не проверяют доступ. Чтение и worker должны использовать
одинаковые настройки моделей и `ANALYTICS_TRIAGE_ENABLED`.

`relevance/kind/priority` сохраняются в `CompanyImpact.triage` вместе с фактическим
провайдером, политикой, версией контекста, временем и задержкой. Триаж — непроверенная
подсказка для полного анализа. `irrelevant` не скрывает новость, `kind` не заменяет
доказанный эффект, `priority` не меняет urgency или порядок сводки. Оценка по полному
EvidencePack и проверки ссылок выполняются независимо от триажа.

Успешный триаж сохраняется отдельно в tenant/company scope: после сбоя полного
анализа повторная попытка использует сохранённое решение, в том числе без checkpoint.
Изменение контекста, primary/fallback модели, URL, вопросов или политики инвалидирует
результат. Уже сохранённый fallback переиспользуется до такой инвалидации.
При отсутствии фактов или неактивном событии триаж пропускается. Слишком большой
контекст не обрезается: сохраняется `skipped_input_limit`, полный анализ продолжает
работать со своим обычным лимитом. Под инструкции fallback резервируются 4000 символов.

Адаптер использует контракт [TypeSafe OpenAPI](https://api.typesafe.ai/openapi.json):
проверяет модель и choice-ответы, обязательные usage, ограничивает timeout и запрещает
redirects. Ошибки и локальный RPM переключают на LLM через circuit cooldown.
`metrics` включает System One как stage `systemone`: запросы, token usage, статус и
задержку; fallback учитывается обычным LLMClient. Цены в рублях не предполагаются.

Демонстрации всех шагов выполняются через настоящий router и HTTP MockTransport,
без `.env.local`, реальных ключей и запросов к внешнему API:

```bash
.venv/bin/python -m orchestrator.analytics demo --triage-mode systemone
.venv/bin/python -m orchestrator.analytics demo --triage-mode fallback
```

Для проверки сохранения в PostgreSQL к любой из команд можно добавить
`--postgres-test-dsn` с явной loopback БД `analytics_test_*`, как в примере выше.

## Контракт будущего подключения

`create_router(service, authorize, authorize_ingestion=...)` возвращает APIRouter с
префиксом `/v1/analytics`. `authorize` обязан вернуть Scope после проверки прав
пользователя на tenant/company. Scope нельзя брать из request body или недоверенных
заголовков. Отдельный `authorize_ingestion` нужен для записи в общий архив;
без него `POST /news` всегда запрещён. Это не реализация пользовательской авторизации.

| Путь | Операция |
| --- | --- |
| `POST /news` | Общий ingestion и анализ разрешённой компании; отдельный ingest principal |
| `PUT /company?expected_revision=N` | Optimistic update профиля |
| `POST /documents` | Base64 файла → знания и job_id |
| `POST /events/{id}/analyze` | Подготовка воздействия и ситуаций |
| `GET /situation`, `GET /issues` | Сохранённые результаты; offset/limit для списка |
| `GET /issues/{id}` | Карточка, опционально `?version=N` |
| `GET /issues/{id}/evidence`, `/history` | Закреплённые источники и версии |
| `GET/PATCH /issues/{id}/state` | Персональные read/pinned/workflow |
| `POST /issues/{id}/questions` | Чат с request_id и закреплённой версией |
| `GET /conversations/{id}` | Сохранённый чат только этого пользователя |
| `POST /refresh`, `GET /jobs/{id}` | Очередь и статус; `retry_failed=true` для явного повтора |

Ошибки контракта — 422, чужой/отсутствующий объект — 404, конфликт ревизий — 409,
бюджет/RPM — 429, недоступность модели — 503. Служебные ошибки не становятся
пустым успешным ответом. Подключение к backend/frontend оставлено отдельным совместным шагом.

## Проверка и эксплуатационные ограничения

```bash
.venv/bin/python -m unittest discover -s orchestrator/tests -q
.venv/bin/python -m unittest discover -s orchestrator/analytics/tests -q
# Полные PG/pgvector/checkpoint проверки; только отдельная тестовая БД.
ANALYTICS_TEST_DATABASE_URL="$ANALYTICS_DATABASE_URL" .venv/bin/python -m unittest discover -s orchestrator/tests -q
ANALYTICS_TEST_DATABASE_URL="$ANALYTICS_DATABASE_URL" .venv/bin/python -m unittest discover -s orchestrator/analytics/tests -q
.venv/bin/python -m pip check
```

Без `ANALYTICS_TEST_DATABASE_URL` PG-тесты явно пропускаются. Unit tests не вызывают
внешний API. `evaluation.compare_pipelines` запускает реальные варианты на одинаковых
fixtures/as_of/context_budget и считает recall, precision, label accuracy, latency,
переданные модельным адаптером calls/tokens и пропуски. `compare_retrieval` отдельно
проверяет объединение заранее заданных каналов A/B/C/D. Синтетические результаты
не доказывают выигрыш архитектуры на реальных данных.

`cleanup` — явная административная операция; срок берётся из
`ANALYTICS_OPERATIONAL_RETENTION_DAYS` (30 дней по умолчанию):

```bash
.venv/bin/python -m orchestrator.analytics cleanup
```

Она удаляет старый cache, завершённые call logs, истёкшие budget blocks и checkpoints
завершённых impact runs. Активные runs и бизнес-история сохраняются. Run/audit records
сохраняются для воспроизводимости; политика удаления корпоративных данных при
удалении аккаунта должна быть согласована вместе с backend.

Лимиты top_k, глубины графа, размера файлов/контекста и debounce — инженерные стартовые
настройки, не результат калибровки. Большой документ, не помещающийся в лимит модели,
завершается явной ошибкой `input_limit`; массовая пакетная extraction не реализована.
Для MVP используется exact vector search и обход небольшого графа в Python,
candidate selection по умолчанию анализирует все явно переданные компании.
Нагрузочное тестирование, размеченный датасет, проверка живого LLM/Graphify и цены
моделей нужны до использования в рабочем потоке. Расчёт стоимости в рублях не выдумывается:
`estimated_cost=null`, сохраняются фактические usage и задержки.
