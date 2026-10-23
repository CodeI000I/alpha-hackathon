# Прототип аналитического пайплайна — отчёт

Дата: 23 октября 2026. Исходная ветка `ai-orchestrator` проверена и обновлена
`git pull --ff-only`: `a7f4f19` → `b0cb4a4` (два изменения парсера).
Код подготовлен в отдельном checkout `alpha-hackathon` в рабочем каталоге ChatGPT.
После проверки пользователь отдельно поручил commit и push в `ai-orchestrator`.
Исходный checkout в `~/Dev/alpha-hackathon` получил только pull.
Backend, frontend, deployment и регистрация router не изменялись.

## Что работает

- PostgreSQL — источник истины: версионированные бизнес-записи, атомарные изменения,
  optimistic concurrency, advisory locks, миграции, GIN/FTS и pgvector exact search.
  Память используется только для временных тестов/демо.
- Общий архив статей и нормализованных событий: source/news_id/revision,
  дедупликация, поправки, сохранение старых источников, отмена и повторная активация.
  Время события не подменяется временем публикации. Одинаковый текст в другой день
  сам по себе не объединяет события без времени.
- Версионированные профили и документы TXT/MD/HTML/PDF/DOCX; русско-английский OCR
  сканов; оригиналы, цитаты, chunk locators, статусы ошибок и атомарная публикация
  извлечённых фактов/связей вместе с готовой ревизией документа.
- Retrieval объединяет точные связи, BM25, PostgreSQL FTS, локальные semantic embeddings
  и ограниченные типизированные графовые пути. Учитываются tenant/company, источники,
  версии и временная применимость. Сбой embeddings в retrieval явно отмечается как
  fallback, а не выдаётся за семантический поиск.
- Проверяемые ImpactAssessment и маршруты accepted/irrelevant/needs_context/inconsistent;
  неизвестное не становится отрицательным фактом. Техническая ошибка сохраняет failed run.
  Политика, версии источников и знаний входят в invalidation/checkpoint keys.
- CompanyImpact группируются по подтверждённой общей exposure, фактору и горизонту.
  BusinessIssue сохраняют версии оснований. Разнонаправленные воздействия остаются mixed;
  вероятности и денежные эффекты не суммируются.
- Сводка сохраняется заранее, содержит приоритеты, изменения и версии ситуаций.
  Чтение не вызывает модель. Новая информация либо наступление срока применимости
  делает прежний результат `current=false` до пересчёта.
- Обновления профиля/документа ставят пересчёт архива в очередь. Есть debounce,
  срочные обновления, bounded retries, lease, budget pause и явный повтор failed jobs.
  Impact workflow восстанавливается из PostgreSQL checkpoints LangGraph.
- Чат закреплён за версией ситуации и user scope; повтор request_id идемпотентен,
  гипотетические вопросы не меняют факты. Сохраняются прочитанность, закрепление,
  пользовательский статус, история ситуаций и сообщений.
- Незарегистрированный router и CLI. Чужие evidence/chat недоступны; запись в общий
  новостной архив требует отдельного ingestion-authorizer и запрещена по умолчанию.
- Метрики calls/tokens/latency/status/model, сохранение budget block между запусками,
  явная очистка старых operational данных/checkpoints с сохранением бизнес-истории.
- Graphify — отключённый по умолчанию импорт подготовленного JSON с проверкой цитат
  и ссылок. Базовый пайплайн работает без Graphify.

## Принятые решения

1. Переиспользованы `LLMClient`, канонический hash, Pydantic-контракты evidence/Answer,
   русский tokenizer/BM25 и HTML cleaner парсера. Старый SQLite `/rank` сохранён;
   в нём исправлены freshness политики и терминальное состояние исчерпанных попыток.
2. Новые доменные модели строго валидируются и сохраняются как append-only JSONB
   записи со scope/version ключами. Это компактнее отдельной ORM-иерархии и удобно
   для меняющегося прототипа. Сложные запросы и граф пока рассчитаны на небольшой корпус.
3. LangGraph checkpoint используется на цепочке retrieval → assessment → save;
   ingestion, synthesis, snapshot и chat реализованы идемпотентными service operations
   и очередью. Checkpoints не заменяют бизнес-данные. Успешные модельные шаги кешируются.
4. Лексический режим включён по умолчанию. Семантический режим использует локальную
   закреплённую sentence-transformer модель, а не выдуманный embeddings API шлюза.
   Совместимость размерностей и версий vectors проверяется на записи и чтении.
5. Все явно переданные компании анализируются в baseline; indexed candidate mode
   оставлен опцией с аудитом причин. Численные relevance thresholds старого контура
   не используются как доказанная политика нового пайплайна.
6. Три агента `gpt-6-luna` разделили persistence, знания/retrieval и synthesis/tests.
   Каждый применял Ponytail и Agent Skills. Основной агент интегрировал код, проверял
   решения и закрыл найденные гонки, freshness и права ingestion.

## Проверка

Использовались Python 3.12.14, PostgreSQL 17.11, pgvector 0.8.7, psycopg 3.3.6.
PostgreSQL был запущен отдельным временным cluster на loopback:55439; рабочая БД,
командный API-ключ и backend/frontend команды не использовались.
После проверок временный PostgreSQL остановлен. Данные остались в
`/private/tmp/alfa-analytics-pg`; offline demo запускается без него.

| Проверка | Результат |
| --- | --- |
| `unittest discover -s orchestrator/tests` с тестовым DSN | **82 passed**, без skips |
| `unittest discover -s orchestrator/analytics/tests` с тестовым DSN | **73 passed**, без skips |
| `unittest discover -s parser_service/tests` с отдельной parser test DB | **120 passed**, без skips |
| `pip check` | Нет конфликтующих установленных зависимостей |
| Offline demo через настоящий LLMClient + MockTransport | 3 события, 1 mixed issue, обновление договора и истории, чтение: 0 модельных вызовов |
| То же демо с PostgresStore + PostgresSaver | Успешно; повторные запуски в той же тестовой БД также успешны |
| Сбой на assess и продолжение с PostgreSQL checkpoint | Продолжение с assess; готовый impact сохранён |
| Конкурентные версии, rollback, shared locks и очистка checkpoints | Успешно, включая гонку cleanup с возобновлением run |
| Локальная multilingual модель, offline encode | 384 измерения, реальные вектора; smoke на русских фразах |
| Русский сканированный PDF | Текст извлечён OCR с локальными eng/rus данными |
| Независимый review | Исправлены stale source cache, явный retry failed job, DSN hostaddr, ingestion ACL; prompt/config policy changes инвалидируют результаты |

Сторонние SWIG/ONNX предупреждения не были ошибками тестов. Тесты не доказывают
правильность будущих ответов живой LLM; они проверяют контракт, orchestration,
данные, отказоустойчивость и отсутствие запрещённых побочных эффектов.

### Сценарии спецификации

| Сценарии | Где проверяются |
| --- | --- |
| T01: разные договоры компаний | `analytics/tests/test_service.py` |
| T02–T05: косвенная связь, дедупликация, multi-event и mixed | `test_acceptance.py`, `test_knowledge.py`, `test_synthesis.py`, demo |
| T06–T09: unknown, новые знания, повторы и temporal update | `test_service.py`, `test_acceptance.py`, `test_knowledge.py` |
| T10–T11: недоказанное ребро и выдуманная ссылка | `test_knowledge.py`, `test_acceptance.py`, `test_synthesis.py` |
| T12–T15: старые активные ситуации, пустая сводка, concurrency, budget | `test_acceptance.py`, `orchestrator/tests/test_postgres.py` |
| T16–T18: гипотезы, изоляция, prompt injection как данные | `test_service.py`, `test_router.py`, `test_acceptance.py` |
| T19–T20: косметика summary, отмена/возврат события | `test_acceptance.py`, `test_synthesis.py` |

T18 проверяет разделение инструкции/данных, отсутствие tools и секретов в контексте.
Это не adversarial-оценка устойчивости живой модели. Evidence IDs и буквальные цитаты
проверяются программно; семантическая верность причинных выводов требует оценки модели.

## Что остаётся перед рабочим подключением

Прототип готов к изолированному запуску и совместной интеграции. Инструкция и команды:
[orchestrator/analytics/README.md](../orchestrator/analytics/README.md).

- Подключить реальные ingestion/auth/backend/frontend по согласованным контрактам,
  worker/schedule к инфраструктурному планировщику и выбрать operational limits.
- Провести smoke живого модельного шлюза с командным ключом и выделенным бюджетом.
  Здесь реальных LLM-вызовов не было; стоимость в рублях не оценивалась.
- На размеченных данных сравнить retrieval A/B/C/опциональный D, assessment variants
  и top-N summary baseline. Добавлены исполняемый `compare_pipelines` и тесты реальных
  HybridRetriever режимов; синтетические metrics не подтверждают превосходство графа.
- Graphify запускается вне прототипа: реализован проверяемый импорт его нормализованного
  результата, но сам внешний extractor не разворачивался и не оценивался.
- Для длинных документов действует явный лимит LLM-контекста. Пакетная extraction,
  массовая переиндексация корпуса, ANN, нагрузочный sizing и политика удаления аккаунтов
  требуют следующего этапа. Эти ограничения не скрываются успешным пустым результатом.

Локальная `.venv`, модель и OCR-данные подготовлены, но не входят в Git. Их установка
воспроизводится requirements и `prepare_assets`; окружение legacy Python 3.15
в исходном checkout не заменялось. Команд для запуска реальных сервисов не выполнялось.
